"""Opération unique — repasse le job legacy Test_5 à `queued` après backfill.

Avant backfill, le worker a tenté le job legacy et l'a marqué `status=error`
avec `error_msg='import_job_parsing_snapshot_missing'`. Le script
`backfill_test5_legacy_snapshot.py` a posé le snapshot ensuite, mais le
job reste à `error` et le script `requeue_import_decoder_172_failures`
ne reconnaît pas ce marker.

Ce script applique la MÊME logique que `requeue_import_decoder_172_failures`
pour la partie "job → queued" : advisory lock, status='queued',
error_msg=None. Il NE touche pas aux `job.files` (déjà remis à `pending`
par la 1re exécution de `requeue_import_decoder_172_failures`).

Discipline :
- opération UNIQUE sur ce job legacy (hard-codé) ;
- refuse si snapshot encore NULL (le backfill doit avoir eu lieu) ;
- refuse si job.status != 'error' ou si error_msg ne pointe pas sur
  le missing snapshot (idempotence : empêche une re-exécution par
  accident sur un job sain).
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.models import NmfImportJob
from app.services.import_jobs import now
from app.services.import_worker import LOCK_ID


EXPECTED_JOB_ID = "c67112ccda3d4e39aae5bc1ffb171904"
EXPECTED_PROJECT_ID = "d8d14aefa51f"
EXPECTED_MARKER = "import_job_parsing_snapshot_missing"


def main() -> int:
    with engine.connect() as lock:
        acquired = bool(
            lock.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
            ).scalar()
        )
        lock.commit()
        if not acquired:
            print("FAIL: import worker is active — stop it before resuming", file=sys.stderr)
            return 1
        try:
            with SessionLocal() as db:
                job = db.get(NmfImportJob, EXPECTED_JOB_ID)
                if job is None:
                    print(f"FAIL: job {EXPECTED_JOB_ID} introuvable", file=sys.stderr)
                    return 2
                if job.project_id != EXPECTED_PROJECT_ID:
                    print(f"FAIL: project mismatch", file=sys.stderr)
                    return 2
                if job.decode_level is None or job.decoder_version is None:
                    print("REFUSE: snapshot encore NULL — lancer d'abord le backfill",
                          file=sys.stderr)
                    return 3
                if job.status != "error":
                    print(f"REFUSE: job.status={job.status} ≠ 'error' — rien à reprendre",
                          file=sys.stderr)
                    return 3
                if EXPECTED_MARKER not in (job.error_msg or ""):
                    print(f"REFUSE: error_msg ne pointe pas sur '{EXPECTED_MARKER}' — pas notre cas",
                          file=sys.stderr)
                    return 3

                print(f"BEFORE: status={job.status!r} error_msg={job.error_msg!r}")

                job.status = "queued"
                job.error_msg = None
                job.updated_at = now()
                db.commit()
                db.refresh(job)

                print(f"AFTER : status={job.status!r} error_msg={job.error_msg!r}")

                files_summary: dict[str, int] = {}
                for entry in job.files:
                    s = entry.get("status", "?")
                    files_summary[s] = files_summary.get(s, 0) + 1
                print(f"files status : {files_summary}")
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            lock.commit()

    print("\nOK — job remis à queued, worker peut reprendre")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
