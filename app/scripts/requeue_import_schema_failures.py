"""Requeue files rejected solely by the repaired Light schema gap."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.models import NmfImportJob, Project
from app.services.import_jobs import now
from app.services.import_worker import LOCK_ID


ERROR_MARKER = 'column "dci_dci_count" of relation "nmf_event_light" does not exist'


def requeue(job_id: str) -> int:
    with engine.connect() as lock:
        acquired = bool(
            lock.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
            ).scalar()
        )
        lock.commit()
        if not acquired:
            raise RuntimeError("import worker is active; stop it before recovery")
        try:
            with SessionLocal() as db:
                job = db.get(NmfImportJob, job_id)
                if job is None:
                    raise ValueError(f"unknown import job: {job_id}")
                repaired = []
                count = 0
                for entry in job.files:
                    item = dict(entry)
                    if item.get("status") != "error" or ERROR_MARKER not in str(
                        item.get("error_msg") or ""
                    ):
                        repaired.append(item)
                        continue
                    source = Path(str(item.get("path") or ""))
                    if not source.is_file():
                        raise RuntimeError(
                            f"retained source missing for {item.get('filename')}"
                        )
                    item.update(
                        status="pending",
                        error_msg=None,
                        n_captures=0,
                        n_events=0,
                        n_gps=0,
                        decoder_version=None,
                    )
                    repaired.append(item)
                    count += 1

                if count == 0:
                    raise ValueError("no matching schema failures to requeue")
                job.files = repaired
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
    print(f"REQUEUE_IMPORT_SCHEMA_FAILURES job={args.job_id} files={count} verdict=PASS")


if __name__ == "__main__":
    main()
