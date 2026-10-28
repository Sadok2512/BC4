"""Requeue only files hit by the pre-1.7.2 Light textual aggregation bug."""

from __future__ import annotations

import argparse
from pathlib import Path

ERROR_MARKERS = (
    "unsupported operand type(s) for +=: 'float' and 'str'",
    "can't multiply sequence by non-int of type 'float'",
)


def is_decoder_172_failure(item: dict) -> bool:
    message = str(item.get("error_msg") or "")
    return item.get("status") == "error" and any(
        marker in message for marker in ERROR_MARKERS
    )


def requeue(job_id: str) -> int:
    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from app.models import NmfImportJob, Project
    from app.services.import_jobs import now
    from app.services.import_worker import LOCK_ID

    with engine.connect() as lock:
        acquired = bool(
            lock.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}).scalar()
        )
        lock.commit()
        if not acquired:
            raise RuntimeError("import worker is active; stop it before recovery")
        try:
            with SessionLocal() as db:
                job = db.get(NmfImportJob, job_id)
                if job is None:
                    raise ValueError(f"unknown import job: {job_id}")
                files = []
                count = 0
                for original in job.files:
                    item = dict(original)
                    if not is_decoder_172_failure(item):
                        files.append(item)
                        continue
                    source = Path(str(item.get("path") or ""))
                    if not source.is_file():
                        raise RuntimeError(f"retained source missing for {item.get('filename')}")
                    item.update(
                        status="pending",
                        error_msg=None,
                        n_captures=0,
                        n_events=0,
                        n_gps=0,
                        decoder_version=None,
                    )
                    files.append(item)
                    count += 1
                if count == 0:
                    raise ValueError("no matching decoder 1.7.2 failures to requeue")
                job.files = files
                job.status = "queued"
                job.error_msg = None
                job.updated_at = now()
                project = db.get(Project, job.project_id)
                if project is None:
                    raise RuntimeError("job project is missing")
                project.status = "processing"
                project.status_ingest = "importing"
                db.commit()
                return count
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            lock.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    count = requeue(args.job_id)
    print(
        f"REQUEUE_IMPORT_DECODER_172_FAILURES job={args.job_id} "
        f"files={count} VERDICT=PASS"
    )


if __name__ == "__main__":
    main()
