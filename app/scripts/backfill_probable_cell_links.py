"""Backfill probable map links from existing tables, without NMF decoding."""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.kpi.probable_link_materialized import materialize_project
from app.scripts.deploy_guard import guard_bc3_deploy_lock


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--capture-id")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if len(args.reason.strip()) < 10:
        print("VERDICT=FAIL reason=reason_too_short", file=sys.stderr)
        return 2
    if not guard_bc3_deploy_lock(action="backfill_probable_cell_links"):
        return 1
    lock_key = f"populate:{args.project_id}"
    try:
        with engine.connect() as lock:
            acquired = bool(lock.execute(text(
                "SELECT pg_try_advisory_lock(hashtext(:key))"),
                {"key": lock_key}).scalar())
            lock.commit()
            if not acquired:
                print("VERDICT=FAIL reason=project_lock_busy", file=sys.stderr)
                return 3
            try:
                with SessionLocal() as db:
                    result = materialize_project(
                        db, args.project_id, capture_id=args.capture_id
                    )
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),
                             {"key": lock_key})
                lock.commit()
    except Exception as exc:
        print(f"VERDICT=FAIL reason={exc!r}", file=sys.stderr)
        return 1
    print(json.dumps({
        "reason": args.reason,
        "source": "existing_database_tables_no_decode",
        "result": result,
    }, indent=2, default=str))
    print("VERDICT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
