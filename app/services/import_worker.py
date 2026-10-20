"""Single durable import worker; interrupted jobs resume after restart.

A session advisory lock remains held across the enrichment code's commits.
This also prevents two worker replicas from recalculating measurements together.
"""
import logging
import signal
import threading
from pathlib import Path

from sqlalchemy import text
from app.db import SessionLocal, engine
from app.models import NmfImportJob, Project
from app.ingest.nmf import ingest_upload, refresh_project_summary, resolve_decoder
from app.dict.populate import populate_param_occurrence
from app.services.populate_chain import run_populate_chain
from app.services.import_report import build_import_report
from app.services.import_jobs import ACTIVE, job_view, now, update_capture_counts

log = logging.getLogger(__name__)
stop = threading.Event()
LOCK_ID = 741629305


def run_job(db, job):
    project = db.get(Project, job.project_id)
    handle = resolve_decoder()
    if not handle.available:
        raise RuntimeError('Décodeur NMF indisponible')
    job.status = 'decoding'
    db.commit()
    for index in range(len(job.files)):
        if stop.is_set():
            return  # Durable unfinished job will resume on the next startup.
        entry = dict(job.files[index])
        if entry['status'] in ('done', 'error'):
            continue
        entry['status'] = 'decoding'
        job.files = [entry if i == index else f for i, f in enumerate(job.files)]
        job.updated_at = now()
        db.commit()
        # Ingest commits staging atomically. If the process dies before the
        # manifest commit, the SHA-256 lookup safely finds the existing file.
        try:
            with Path(entry['path']).open('rb') as stream:
                nmf = ingest_upload(db, project, stream, entry['filename'], handle, populate=False)
            entry.update(status=nmf.status, n_captures=nmf.n_captures,
                n_events=nmf.n_events, n_gps=nmf.n_gps,
                decoder_version=nmf.decoder_version, error_msg=nmf.error_msg)
        except Exception as exc:
            db.rollback()
            entry.update(status='error', error_msg=str(exc))
            log.exception('File import failed job=%s file=%s', job.id, entry['filename'])
        job.files = [entry if i == index else f for i, f in enumerate(job.files)]
        job.updated_at = now()
        update_capture_counts(db, project)
        db.commit()
        log.info('Import %s: %s/%s files processed', job.id, index + 1, len(job.files))

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
