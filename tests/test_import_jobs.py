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
from app.services.overview import project_to_schema


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    for model in (Project, NmfFile, NmfImportJob):
        model.__table__.create(engine)
    monkeypatch.setattr(queue, 'NMF_SOURCE_DIR', str(tmp_path))
    with Session(engine) as session:
        session.add(Project(id='p', owner_id='test-owner', visibility='private', name='Queue test', geography='', center_lng=0,
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
    def ingest(db, project, stream, filename, handle, *, populate, parsing_snapshot):
        calls.append((filename, populate, dict(parsing_snapshot)))
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
    assert len(calls) == 62 and all(populate is False for _, populate, _ in calls)
    assert all(call[2]["decode_level"] == "light" for call in calls)
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
    assert calls[0][:2] == ('file-1.nmf', False)
    chain.assert_called_once()
    assert job.report['files_done'] == 2


def test_file_error_is_not_reported_as_success(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    setup_worker(monkeypatch)
    original = worker.ingest_upload
    def failing(db, project, stream, filename, handle, *, populate, parsing_snapshot):
        if filename == 'file-0.nmf':
            raise ValueError('Malformed file')
        return original(
            db, project, stream, filename, handle,
            populate=populate, parsing_snapshot=parsing_snapshot,
        )
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


def test_report_recovery_does_not_decode_or_repopulate(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    job.files = [dict(f, status='done', n_captures=1, n_events=4) for f in job.files]
    job.status = 'error'
    job.error_msg = 'TEST idle timeout after population commit'
    db.commit()
    calls, summary, dictionary, chain = setup_worker(monkeypatch)
    worker.finalize_import_report(db, job, db.get(Project, 'p'))
    assert not calls
    summary.assert_not_called(); dictionary.assert_not_called(); chain.assert_not_called()
    assert job.status == 'done' and job.error_msg is None
    assert job.report['files_done'] == 2
    assert db.get(Project, 'p').status_ingest == 'ready'


def test_report_recovery_rejects_unfinished_files(db, monkeypatch):
    job = queue.enqueue(db, 'p', uploads())
    setup_worker(monkeypatch)
    with pytest.raises(ValueError, match='unfinished'):
        worker.finalize_import_report(db, job, db.get(Project, 'p'))
    assert job.status == 'queued' and job.report is None


def test_import_job_freezes_parsing_contract_when_enqueued(db):
    project = db.get(Project, 'p')
    project.parse_decode_level = 'light'
    project.parse_binning_mode = 'temporal'
    project.parse_temporal_resolution = '10ms'
    project.parse_spatial_bin_m = None
    db.commit()

    job = queue.enqueue(db, 'p', uploads(1))
    before = {
        'decode_level': job.decode_level,
        'binning_mode': job.binning_mode,
        'temporal_resolution': job.temporal_resolution,
        'spatial_bin_m': job.spatial_bin_m,
        'aggregation_contract_version': job.aggregation_contract_version,
        'decoder_version': job.decoder_version,
    }
    project.parse_decode_level = 'deep'
    project.parse_binning_mode = 'spatial'
    project.parse_temporal_resolution = None
    project.parse_spatial_bin_m = 50
    db.commit()
    db.refresh(job)

    assert before == {
        'decode_level': 'light',
        'binning_mode': 'temporal',
        'temporal_resolution': '10ms',
        'spatial_bin_m': None,
        'aggregation_contract_version': 'query-binning-v1',
        'decoder_version': job.decoder_version,
    }
    assert worker.parsing_snapshot(job) == before


def test_capture_counts_use_measurement_dates_from_file_content(db):
    project = db.get(Project, 'p')
    common = dict(
        project_id='p', size_bytes=1, uploaded_at=queue.now(), status='done',
        decoder_version='test', error_msg=None, n_captures=1, n_events=1, n_gps=0,
    )
    db.add_all([
        NmfFile(id='date-a', filename='a.nmf', sha256='date-a', start_at='11.06.2026 00:01:00.000', **common),
        NmfFile(id='date-b', filename='b.nmf', sha256='date-b', start_at='10.06.2026 23:59:00.000', **common),
    ])
    db.commit()

    queue.update_capture_counts(db, project)

    assert project.period_start == '2026-06-10'
    assert project.period_end == '2026-06-11'
    # Listing also corrects an already-imported legacy project without waiting
    # for another file or mutating source data.
    project.period_start = '2026-10-27'
    project.period_end = '2026-10-27'
    db.flush()
    listing = project_to_schema(project)
    assert listing.periodStart == '2026-06-10'
    assert listing.periodEnd == '2026-06-11'
