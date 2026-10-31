"""Single durable import worker; interrupted jobs resume after restart.

A session advisory lock remains held across the enrichment code's commits.
This also prevents two worker replicas from recalculating measurements together.
"""
import logging
import hashlib
import cProfile
import io
import multiprocessing
import os
import resource
import pstats
import signal
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from sqlalchemy import text
from app.config import settings
from app.db import SessionLocal, engine
from app.models import NmfImportJob, Project
from app.ingest.nmf import ingest_upload, refresh_project_summary, resolve_decoder
from app.dict.populate import populate_param_occurrence
from app.services.populate_chain import run_populate_chain
from app.services.import_report import build_import_report
from app.services.import_jobs import ACTIVE, job_view, now, update_capture_counts
from app.services.import_admission import decide

log = logging.getLogger(__name__)
stop = threading.Event()
LOCK_ID = 741629305


def parsing_snapshot(job):
    """Return the enqueue-time contract or reject an unsnapshotted legacy job."""
    fields = (
        'decode_level', 'binning_mode', 'temporal_resolution', 'spatial_bin_m',
        'aggregation_contract_version', 'decoder_version',
    )
    snapshot = {field: getattr(job, field) for field in fields}
    required = ('decode_level', 'binning_mode', 'aggregation_contract_version', 'decoder_version')
    if any(snapshot[field] is None for field in required):
        raise ValueError('import_job_parsing_snapshot_missing')
    return snapshot


def _entry_result(nmf):
    return dict(status=nmf.status, n_captures=nmf.n_captures,
        n_events=nmf.n_events, n_gps=nmf.n_gps,
        decoder_version=nmf.decoder_version, error_msg=nmf.error_msg)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _print_profile(profile: cProfile.Profile, label: str) -> None:
    stream = io.StringIO()
    raw_stats = pstats.Stats(profile)
    display_stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative')
    display_stats.print_stats(20)
    database_tottime = sum(
        values[2] for func, values in raw_stats.stats.items()
        if any(term in ' '.join(map(str, func)).lower()
               for term in ('psycopg', 'sqlalchemy', 'select.poll', 'cursor'))
    )
    total = raw_stats.total_tt
    database_pct = 100.0 * database_tottime / total if total else 0.0
    print(f'PROFILE {label} total_s={total:.3f} '
          f'postgresql_exclusive_s={database_tottime:.3f} '
          f'postgresql_pct={database_pct:.2f} '
          f'python_other_pct={100.0-database_pct:.2f}', flush=True)
    stages = _profile_stages(raw_stats)
    print('PROFILE ' + label + ' STAGES ' + ' '.join(
        f'{name}={seconds:.3f}s({100.0 * seconds / total if total else 0.0:.2f}%)'
        for name, seconds in stages.items()
    ), flush=True)
    print(f'PROFILE {label} TOP20\n{stream.getvalue()}', flush=True)


def _profile_stages(stats: pstats.Stats) -> dict[str, float]:
    """Partition cProfile exclusive time into decoder pipeline stages."""
    out = {
        'read_split': 0.0,
        'field_conversion': 0.0,
        'asn1_pycrate': 0.0,
        'row_construction': 0.0,
        'light_aggregation': 0.0,
        'writing': 0.0,
        'other': 0.0,
    }
    for (filename, _line, function), values in stats.stats.items():
        own = values[2]
        path = filename.replace('\\', '/').lower()
        ident = f'{path}:{function.lower()}'
        if 'pycrate' in ident or '/app/dict/decode.py' in path:
            stage = 'asn1_pycrate'
        elif path.endswith('/nmf_decoder/source.py') or (
            path.endswith('/bc4_decoder.py')
            and function in {'_fields', '_iter_events', '_parse_meta', 'decode_nmf_file_full'}
        ) or (path.endswith('/nmf_decoder/decoder.py') and function == 'tokenize'):
            stage = 'read_split'
        elif path.endswith('/bc4_decoder.py') or path.endswith('/nmf_decoder/decoder.py'):
            stage = 'field_conversion'
        elif path.endswith('/nmf_decoder/light.py'):
            stage = 'light_aggregation'
        elif (
            (path.endswith('/nmf_decoder/store.py') and function == 'copy_rows')
            or 'psycopg' in path and ('copy' in ident or 'write_row' in ident)
        ):
            stage = 'writing'
        elif path.endswith('/nmf_decoder/store.py'):
            stage = 'row_construction'
        else:
            stage = 'other'
        out[stage] += own
    return out


def _process_file(job_id, index):
    """Spawn-safe file worker with a session advisory lock per content hash."""
    with SessionLocal() as db:
        job = db.get(NmfImportJob, job_id)
        entry = dict(job.files[index])
        project = db.get(Project, job.project_id)
        snapshot = parsing_snapshot(job)
        identity = entry.get('sha256') or entry['path']
        lock_key = f'import-file:{job.project_id}:{identity}'
        locked = db.execute(text('SELECT pg_try_advisory_lock(hashtext(:key))'), {'key': lock_key}).scalar()
        db.commit()
        if not locked:
            return dict(status='locked')
        started = time.monotonic()
        profiler = cProfile.Profile() if os.environ.get('BC4_IMPORT_PROFILE') == 'YES' else None
        try:
            if profiler: profiler.enable()
            handle = resolve_decoder()
            if not handle.available:
                raise RuntimeError('Décodeur NMF indisponible')
            queued_path = Path(entry['path'])
            if entry.get('sha256') and _file_sha256(queued_path) != entry['sha256']:
                raise ValueError('queued_source_sha_mismatch')
            with queued_path.open('rb') as stream:
                nmf = ingest_upload(db, project, stream, entry['filename'], handle,
                    populate=False, parsing_snapshot=snapshot)
            result = _entry_result(nmf)
            result.update(
                worker_elapsed_s=time.monotonic() - started,
                worker_peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            )
            return result
        finally:
            if profiler:
                profiler.disable()
                _print_profile(profiler, f'WORKER file={entry["filename"]}')
            db.rollback()
            db.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': lock_key})
            db.commit()


def _mark_entry(db, job, index, **changes):
    entry = dict(job.files[index])
    entry.update(changes)
    job.files = [entry if i == index else item for i, item in enumerate(job.files)]
    job.updated_at = now()
    db.commit()


def _run_sequential(db, job, project, snapshot, handle):
    """SQLite/unit-test path; production PostgreSQL always uses processes."""
    for index, raw in enumerate(list(job.files)):
        if stop.is_set(): return
        if raw['status'] in ('done', 'error'): continue
        _mark_entry(db, job, index, status='decoding')
        entry = dict(job.files[index])
        try:
            queued_path = Path(entry['path'])
            if entry.get('sha256') and _file_sha256(queued_path) != entry['sha256']:
                raise ValueError('queued_source_sha_mismatch')
            with queued_path.open('rb') as stream:
                result = _entry_result(ingest_upload(db, project, stream,
                    entry['filename'], handle, populate=False,
                    parsing_snapshot=snapshot))
        except Exception as exc:
            db.rollback(); result = dict(status='error', error_msg=str(exc))
            log.exception('File import failed job=%s file=%s', job.id, entry['filename'])
        _mark_entry(db, job, index, **result)
        update_capture_counts(db, project); db.commit()


def _run_parallel(db, job, project, snapshot):
    job_id = job.id
    pending = [i for i, entry in enumerate(job.files)
        if entry['status'] not in ('done', 'error')]
    running = {}
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=settings.import_workers_max, mp_context=context) as pool:
        while pending or running:
            started = False
            while pending and len(running) < settings.import_workers_max and not stop.is_set():
                index = pending[0]; entry = dict(job.files[index])
                size = entry.get('size_bytes') or os.path.getsize(entry['path'])
                decision = decide(size, snapshot['decode_level'], len(running))
                log.info('import_admission file=%s size_bytes=%s estimate_mb=%s '
                    'available_mb=%s decision=%s reason=%s running=%s',
                    entry['filename'], size, decision.estimate_mb,
                    decision.available_mb, decision.decision, decision.reason,
                    decision.running)
                if decision.decision == 'wait': break
                pending.pop(0); _mark_entry(db, job, index, status='decoding')
                running[pool.submit(_process_file, job_id, index)] = (index, size)
                started = True
            if stop.is_set():
                for future in running: future.cancel()
                return
            if not running:
                # Guard below margin: do not spin and do not start a file.
                stop.wait(1); continue
            done, _ = wait(running, timeout=1 if started else None,
                return_when=FIRST_COMPLETED)
            for future in done:
                index, _ = running.pop(future)
                try: result = future.result()
                except Exception as exc:
                    result = dict(status='error', error_msg=str(exc))
                    log.exception('File process failed job=%s index=%s', job_id, index)
                if result.get('status') == 'locked':
                    pending.append(index); _mark_entry(db, job, index, status='pending')
                    continue
                _mark_entry(db, job, index, **result)
                log.info('import_complete index=%s status=%s elapsed_s=%.3f '
                    'peak_rss_mb=%.3f running=%s', index,
                    result.get('status'), result.get('worker_elapsed_s', 0.0),
                    result.get('worker_peak_rss_mb', 0.0), len(running))
                update_capture_counts(db, project); db.commit()


def run_job(db, job):
    previous_expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        return _run_job_unexpired(db, job)
    finally:
        db.expire_on_commit = previous_expire_on_commit


def _run_job_unexpired(db, job):
    project = db.get(Project, job.project_id)
    snapshot = parsing_snapshot(job)
    handle = resolve_decoder()
    if not handle.available:
        raise RuntimeError('Décodeur NMF indisponible')
    job.status = 'decoding'; db.commit()
    if db.get_bind().dialect.name == 'postgresql':
        _run_parallel(db, job, project, snapshot)
    else:
        _run_sequential(db, job, project, snapshot, handle)

    if stop.is_set():
        return
    job.status = 'finalizing'
    job.updated_at = now()
    db.commit()
    # Once per batch, in dependency order: summary, RRC proofs, measurements.
    refresh_project_summary(db, project, populate=False, importing=True)
    if any(f['status'] == 'done' for f in job.files):
        populate_param_occurrence(db, project.id, purge=True)
        db.commit()
        run_populate_chain(db, project)
    finalize_import_report(db, job, project)


def finalize_import_report(db, job, project):
    """Persist the report after enrichment has succeeded; never decode again.

    Recovery callers must first verify the persisted enrichment and acquire
    the worker lock. An unfinished file must never be marked successful here.
    """
    if any(entry['status'] not in ('done', 'error') for entry in job.files):
        raise ValueError('Cannot finalize an import with unfinished files')
    view = job_view(job)
    report = build_import_report(db, project, view.by_file,
        view.files_total, view.files_done, view.files_error)
    job.report = report.model_dump()
    job.status = 'error' if view.files_error else 'done'
    job.error_msg = f'{view.files_error} fichier(s) en échec.' if view.files_error else None
    project.status = 'failed' if view.files_error else 'ready'
    project.status_ingest = 'error' if view.files_error else 'ready'
    job.updated_at = now()
    db.commit()
    # Retain failed inputs for diagnosis. Successful sources were persisted
    # by ingest_upload; only their redundant queue copies can be removed.
    for entry in job.files:
        if entry['status'] == 'done':
            try:
                Path(entry['path']).unlink(missing_ok=True)
            except OSError:
                log.warning('Could not remove queue copy for job=%s', job.id)


def process_next():
    with engine.connect() as lock:
        if not lock.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_ID}).scalar():
            return False
        lock.commit()
        try:
            with SessionLocal() as db:
                from app.services.cell_ref_jobs import process_next as process_cell_ref
                if process_cell_ref(db):
                    return True
                job = db.query(NmfImportJob).filter(NmfImportJob.status.in_(ACTIVE)).order_by(NmfImportJob.created_at).first()
                if job is None:
                    from app.nmf_decoder.jobs import process_next as decode_next
                    return decode_next(db,stop)
                jid = job.id
                try:
                    run_job(db, job)
                except Exception as exc:
                    log.exception('Import failed job=%s', jid)
                    db.rollback()
                    job = db.get(NmfImportJob, jid)
                    if job is not None:
                        job.status = 'error'
                        job.error_msg = str(exc)
                        job.updated_at = now()
                        project = db.get(Project, job.project_id)
                        project.status = 'failed'
                        project.status_ingest = 'error'
                        db.commit()
                return True
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_ID})
            lock.commit()


def main():
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            if process_next():
                continue
        except Exception:
            log.exception('Import queue unavailable; retrying')
        stop.wait(2)


if __name__ == '__main__':
    main()
