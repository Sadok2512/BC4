"""Durable uploads. No decoding is performed in an HTTP request."""
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import uuid

from fastapi import HTTPException
from sqlalchemy import func

from app.ingest.nmf import NMF_SOURCE_DIR, BodyTooLarge, spool_and_hash
from app.models import NmfFile, NmfImportJob, Project
from app.schemas.ingest import NmfFileEntry, NmfImportJobView

ACTIVE = ('queued', 'decoding', 'finalizing')


def now():
    return datetime.now(timezone.utc)


def job_view(job):
    entries = [NmfFileEntry(**{k: v for k, v in f.items() if k != 'path'}) for f in job.files]
    return NmfImportJobView(
        id=job.id, project_id=job.project_id, status=job.status,
        files_total=len(entries), files_done=sum(f.status == 'done' for f in entries),
        files_error=sum(f.status == 'error' for f in entries), by_file=entries,
        error_msg=job.error_msg, report=job.report,
    )


def active_job(db, project_id):
    return db.query(NmfImportJob).filter(
        NmfImportJob.project_id == project_id, NmfImportJob.status.in_(ACTIVE)
    ).first()


def enqueue(db, project_id, uploads):
    # Serialize submissions to the same project; staged files are committed
    # only after every input is durable. A rejected request leaves no job.
    project = db.query(Project).filter(Project.id == project_id).with_for_update().one_or_none()
    if project is None:
        raise HTTPException(404, 'Projet introuvable')
    existing = active_job(db, project_id)
    if existing:
        raise HTTPException(409, {'message': 'Un import est déjà en cours pour ce projet.', 'job_id': existing.id})
    jid = uuid.uuid4().hex
    directory = Path(NMF_SOURCE_DIR) / 'jobs' / jid
    entries = []
    try:
        directory.mkdir(parents=True)
        for index, upload in enumerate(uploads):
            target = directory / f'{index}.nmf'
            with target.open('wb') as out:
                spool_and_hash(upload.file, out)
                out.flush()
                os.fsync(out.fileno())
            entries.append(dict(path=str(target), filename=upload.filename or 'unnamed.nmf',
                status='pending', n_captures=0, n_events=0, n_gps=0,
                decoder_version=None, error_msg=None))
        job = NmfImportJob(id=jid, project_id=project.id, status='queued',
            created_at=now(), updated_at=now(), files=entries)
        db.add(job)
        project.status = 'processing'
        project.status_ingest = 'importing'
        db.commit()
        return job
    except Exception as exc:
        db.rollback()
        shutil.rmtree(directory, ignore_errors=True)
        if isinstance(exc, BodyTooLarge):
            raise HTTPException(413, 'Fichier NMF trop volumineux') from exc
        raise
    finally:
        for upload in uploads:
            upload.file.close()


def update_capture_counts(db, project):
    captures, events = db.query(func.sum(NmfFile.n_captures), func.sum(NmfFile.n_events)).filter(
        NmfFile.project_id == project.id, NmfFile.status == 'done').one()
    project.captures = int(captures or 0)
    project.n_captures_ingest = int(captures or 0)
    project.n_events_ingest = int(events or 0)
