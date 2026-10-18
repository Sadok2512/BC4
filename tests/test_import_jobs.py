"""Isolated queue tests; no production database or decoder required."""
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Project, NmfFile, NmfImportJob
from app.schemas.ingest import NmfImportReport
from app.services import import_jobs as queue, import_worker as worker


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    for model in (Project, NmfFile, NmfImportJob):
        model.__table__.create(engine)
    monkeypatch.setattr(queue, 'NMF_SOURCE_DIR', str(tmp_path))
    with Session(engine) as session:
        session.add(Project(id='p', name='Queue test', geography='', center_lng=0,
            center_lat=0, operators=[], technologies=[], services=[], bands=[],
            departements=[], period_start='', period_end='', captures=0,
            imported_at='', status='processing', status_ingest='draft'))
        session.commit()
        yield session
    worker.stop.clear()


def uploads(n=2):
    return [UploadFile(filename=f'file-{i}.nmf', file=io.BytesIO(f'content-{i}'.encode())) for i in range(n)]


def test_accepts_durable_files_without_decoding_and_rejects_overlap(db):
    job = queue.enqueue(db, 'p', uploads())
    assert job.status == 'queued'
    assert [Path(f['path']).read_bytes() for f in job.files] == [b'content-0', b'content-1']
    view = queue.job_view(job).model_dump()
    assert view['files_total'] == 2 and view['files_done'] == 0
    assert 'path' not in view['by_file'][0]
    with pytest.raises(HTTPException) as err:
        queue.enqueue(db, 'p', uploads())
    assert err.value.status_code == 409
    assert db.query(NmfImportJob).count() == 1


def setup_worker(monkeypatch):
    calls = []
    def ingest(db, project, stream, filename, handle, *, populate):
        calls.append((filename, populate))
        return SimpleNamespace(status='done', n_captures=1, n_events=4,
            n_gps=2, decoder_version='test', error_msg=None)
    monkeypatch.setattr(worker, 'resolve_decoder', lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(worker, 'ingest_upload', ingest)
    summary, dictionary, chain = Mock(), Mock(), Mock()
    monkeypatch.setattr(worker, 'refresh_project_summary', summary)
    monkeypatch.setattr(worker, 'populate_param_occurrence', dictionary)
    monkeypatch.setattr(worker, 'run_populate_chain', chain)
    monkeypatch.setattr(worker, 'build_import_report', lambda db, p, entries, total, done, error:
        NmfImportReport(files_received=total, files_done=done, files_error=error,
            by_file=entries, n_captures=done, n_events=done*4,
            gps_coverage_pct=None, operators_seen={}, technos_seen={}))
    return calls, summary, dictionary, chain


def test_62_files_finalized_once_and_not_per_file(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads(62))
    calls, summary, dictionary, chain = setup_worker(monkeypatch)
    worker.run_job(db, job)
    assert len(calls) == 62 and all(populate is False for _, populate in calls)
    summary.assert_called_once_with(db, db.get(Project, 'p'), populate=False, importing=True)
    dictionary.assert_called_once()
    chain.assert_called_once()
    assert job.status == 'done' and job.report['files_done'] == 62
    assert db.get(Project, 'p').status == 'ready'


def test_interrupted_job_resumes_skipping_completed_files(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    entries = list(job.files)
    entries[0] = dict(entries[0], status='done', n_captures=1, n_events=4)
    entries[1] = dict(entries[1], status='decoding')
    job.files = entries
    job.status = 'decoding'
    db.commit()
    calls, _, _, chain = setup_worker(monkeypatch)
    worker.run_job(db, job)
    assert calls == [('file-1.nmf', False)]
    chain.assert_called_once()
    assert job.report['files_done'] == 2


def test_file_error_is_not_reported_as_success(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    setup_worker(monkeypatch)
    original = worker.ingest_upload
    def failing(db, project, stream, filename, handle, *, populate):
        if filename == 'file-0.nmf':
            raise ValueError('Malformed file')
        return original(db, project, stream, filename, handle, populate=populate)
    monkeypatch.setattr(worker, 'ingest_upload', failing)
    worker.run_job(db, job)
    assert job.status == 'error'
    assert job.report['files_error'] == 1 and job.report['files_done'] == 1
    assert job.files[0]['error_msg'] == 'Malformed file'
    assert db.get(Project, 'p').status == 'failed'


def test_rejected_oversize_batch_leaves_no_job_or_partial_files(db, monkeypatch, tmp_path):
    monkeypatch.setattr(queue, 'spool_and_hash', Mock(side_effect=queue.BodyTooLarge()))
    with pytest.raises(HTTPException) as err:
        queue.enqueue(db, 'p', uploads())
    assert err.value.status_code == 413
    assert db.query(NmfImportJob).count() == 0
    assert list((tmp_path / 'jobs').iterdir()) == []
    assert db.get(Project, 'p').status_ingest == 'draft'


def test_finalization_failure_is_persisted(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    setup_worker(monkeypatch)
    monkeypatch.setattr(worker, 'run_populate_chain', Mock(side_effect=RuntimeError('Finalization failed')))
    class Lock:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return SimpleNamespace(scalar=lambda: True)
        def commit(self): pass
    class DBContext:
        def __enter__(self): return db
        def __exit__(self, *args): pass
    monkeypatch.setattr(worker, 'engine', SimpleNamespace(connect=Lock))
    monkeypatch.setattr(worker, 'SessionLocal', DBContext)
    assert worker.process_next()
    db.refresh(job)
    assert job.status == 'error'
    assert job.error_msg == 'Finalization failed'
    assert job.report is None
    assert db.get(Project, 'p').status == 'failed'
    assert all(Path(f['path']).exists() for f in job.files)


def test_missing_measurements_do_not_crash_finalization(monkeypatch):
    from app.measure import profiling
    monkeypatch.setattr(profiling, 'profile_field', lambda db, pid, code, field:
        SimpleNamespace(field=field, n_valid=0, avg=None))
    mapping = profiling.profile_cellmeas(None, 'empty')
    assert mapping.rsrp is None and mapping.rsrq is None
    assert mapping.rssi is None and mapping.sinr is None
    assert not any('ambigu: cell0_c8' in line for line in mapping.debug)
