"""Rattrape le catalogue réseau sans re-décoder les captures.

Usage:
  python -m app.scripts.backfill_dict_network_catalog PROJECT_ID \
    --reason "justification opérateur"
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import text

from app.dict.materialized import materialize_network_catalog
from app.scripts.deploy_guard import guard_bc3_deploy_lock


def _snapshot(db, project_id):
    row = db.execute(text("""SELECT s.*,
      (SELECT count(*) FROM dict_network_catalog_entry e
       WHERE e.project_id=s.project_id AND e.generation=s.generation) AS stored_rows
      FROM dict_network_catalog_state s WHERE s.project_id=:pid"""),
      {"pid": project_id}).mappings().one_or_none()
    return dict(row) if row else None


def _audit_path():
    directory = Path(__file__).resolve().parents[2] / "audit" / "dict-network-catalog"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", nargs="?")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if not args.project_id:
        print("VERDICT=FAIL reason=project_id_required", file=sys.stderr)
        return 2
    if not args.reason or len(args.reason.strip()) < 10:
        print("VERDICT=FAIL reason=reason_too_short", file=sys.stderr)
        return 2
    if not guard_bc3_deploy_lock(action="backfill_dict_network_catalog"):
        return 1
    from app.db import SessionLocal, engine
    report = None
    try:
        with engine.connect() as lock:
            key = f"populate:{args.project_id}"
            acquired = bool(lock.execute(text(
                "SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}).scalar())
            lock.commit()
            if not acquired:
                print("VERDICT=FAIL reason=project_lock_busy", file=sys.stderr)
                return 3
            try:
                with SessionLocal() as db:
                    exists = db.execute(text("SELECT 1 FROM projects WHERE id=:pid"),
                                        {"pid": args.project_id}).scalar()
                    if not exists:
                        print("VERDICT=FAIL reason=project_not_found", file=sys.stderr)
                        return 4
                    before = _snapshot(db, args.project_id)
                    result = materialize_network_catalog(db, args.project_id)
                    after = _snapshot(db, args.project_id)
                    report = {
                        "op_id": uuid4().hex,
                        "when": datetime.now(timezone.utc).isoformat(),
                        "project_id": args.project_id,
                        "reason": args.reason,
                        "source": "existing_database_tables_no_decode",
                        "before": before, "after": after, "result": result,
                    }
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),
                             {"key": key})
                lock.commit()
    except Exception as exc:
        print(f"VERDICT=FAIL reason={exc!r}", file=sys.stderr)
        return 1
    audit = _audit_path()
    audit.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"VERDICT=PASS audit={audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
