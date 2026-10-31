"""Durable, size-bounded cell-reference upload jobs.

The HTTP request only persists the multipart file and a queued history row.
The existing import worker consumes that row and calls the same streaming
ingestion service as ``reimport_cell_reference``. Interrupted running jobs are
idempotently resumed from their persisted source file.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.cell_ref_ingest import BodyTooLarge, ingest_csv_stream, spool_upload


log = logging.getLogger(__name__)
REFERENCE_DIR = Path(os.environ.get("BC4_REFERENCES_DIR", "/var/lib/bc4/references"))
ACTIVE = ("queued", "running")


def empty_report(**extra) -> dict:
    report = {
        "rows_read": 0,
        "rows_loaded": 0,
        "rows_rejected": 0,
        "rejected_by_reason": {},
        "distinct_eci": 0,
        "distinct_nci": 0,
        "by_rat": {},
        "bands_unmapped": {},
        "etat_breakdown": {},
        "arcep_breakdown": {},
        "snapshot_date": None,
    }
    report.update(extra)
    return report


def enqueue(db: Session, upload: UploadFile, actor: str) -> dict:
    filename = upload.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, {"code": "FORMAT_UNSUPPORTED", "message": "seul CSV supporté"})
    job_id = f"ref-{uuid4().hex[:12]}"
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    source = REFERENCE_DIR / f"{job_id}.csv"
    partial = REFERENCE_DIR / f".{job_id}.part"
    try:
        with partial.open("w+b") as stream:
            size = spool_upload(upload.file, stream)
        if size == 0:
            raise HTTPException(400, {"code": "EMPTY_FILE", "message": "fichier vide"})
        partial.replace(source)
        db.execute(text("""
            INSERT INTO reference_import
                (id,filename,uploaded_at,actor,snapshot_date,rows_read,
                 rows_loaded,rows_rejected,status,report,source_path)
            VALUES (:id,:filename,:uploaded_at,:actor,NULL,0,0,0,'queued',
                    CAST(:report AS JSON),:source_path)
        """), {
            "id": job_id,
            "filename": filename,
            "uploaded_at": datetime.now(timezone.utc),
            "actor": actor,
            "report": json.dumps(empty_report(job_status="queued", source_bytes=size)),
            "source_path": str(source),
        })
        db.commit()
    except BodyTooLarge as exc:
        db.rollback()
        partial.unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        raise HTTPException(413, {"code": "PAYLOAD_TOO_LARGE", "message": str(exc)}) from exc
    except Exception:
        db.rollback()
        partial.unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()
    return {"job_id": job_id, "status": "queued", "filename": filename, "source_bytes": size}


def get_job(db: Session, job_id: str) -> dict:
    row = db.execute(text("""
        SELECT id,filename,uploaded_at,status,rows_read,rows_loaded,rows_rejected,report
        FROM reference_import WHERE id=:id
    """), {"id": job_id}).mappings().first()
    if row is None:
        raise HTTPException(404, {"code": "JOB_NOT_FOUND", "message": "job inconnu"})
    report = dict(row["report"] or {})
    progress = 100 if row["status"] in ("completed", "empty", "failed") else (
        10 if row["status"] == "running" else 0
    )
    return {
        "job_id": row["id"], "filename": row["filename"],
        "uploaded_at": row["uploaded_at"], "status": row["status"],
        "progress_percent": progress,
        "rows_read": int(row["rows_read"]), "rows_loaded": int(row["rows_loaded"]),
        "rows_rejected": int(row["rows_rejected"]),
        "report": report if row["status"] in ("completed", "empty") else None,
        "error": report.get("error"),
    }


def process_next(db: Session) -> bool:
    """Consume one queued/running job; caller is the single import worker."""
    row = db.execute(text("""
        SELECT id,filename,actor,source_path FROM reference_import
        WHERE status=ANY(:statuses) AND source_path IS NOT NULL
        ORDER BY uploaded_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    """), {"statuses": list(ACTIVE)}).mappings().first()
    if row is None:
        return False
    job = dict(row)
    acquired = bool(db.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('cell_ref:reimport'))"
    )).scalar())
    db.commit()
    if not acquired:
        return False
    try:
        db.execute(text("""
            UPDATE reference_import SET status='running',
              report=CAST(:report AS JSON) WHERE id=:id
        """), {
            "id": job["id"],
            "report": json.dumps(empty_report(job_status="running")),
        })
        db.commit()
        source = Path(job["source_path"])
        with source.open("rb") as stream:
            ingest_csv_stream(
                db, stream, filename=job["filename"], actor=job["actor"],
                import_id=job["id"],
            )
        log.info("cell reference job completed id=%s", job["id"])
    except Exception as exc:
        db.rollback()
        reason = str(exc) or type(exc).__name__
        report = empty_report(
            job_status="failed",
            error={"code": type(exc).__name__, "reason": reason[:500]},
        )
        db.execute(text("""
            UPDATE reference_import SET status='failed',report=CAST(:report AS JSON)
            WHERE id=:id
        """), {"id": job["id"], "report": json.dumps(report)})
        db.commit()
        log.exception("cell reference job failed id=%s", job["id"])
    finally:
        db.execute(text(
            "SELECT pg_advisory_unlock(hashtext('cell_ref:reimport'))"
        ))
        db.commit()
    return True
