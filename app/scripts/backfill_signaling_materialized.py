"""Rattrape les projections Signaling sans re-décoder les captures.

Usage:
  python -m app.scripts.backfill_signaling_materialized PROJECT_ID \
    [--capture-id CAPTURE_ID] --reason "justification opérateur"
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.scripts.deploy_guard import guard_bc3_deploy_lock
from app.signaling.materialized import materialize_project


def _snapshot(db, project_id, capture_id=None):
    params = {"pid": project_id}
    clause = ""
    if capture_id:
        clause = " AND c.capture_id=:cap"
        params["cap"] = capture_id
    rows = db.execute(text("""SELECT c.capture_id,c.decoder_version,
      m.generation,m.decoder_version AS materialized_decoder_version,m.built_at,
      (SELECT count(*) FROM signaling_materialized_event e
        WHERE e.project_id=c.project_id AND e.capture_id=c.capture_id
          AND e.generation=m.generation) AS events,
      (SELECT count(*) FROM signaling_materialized_point p
        WHERE p.project_id=c.project_id AND p.capture_id=c.capture_id
          AND p.generation=m.generation) AS points
      FROM nmf_capture c LEFT JOIN signaling_materialized_capture m
        USING(project_id,capture_id)
      WHERE c.project_id=:pid""" + clause +
      " ORDER BY c.project_id,c.capture_id"), params).mappings()
    return [dict(row) for row in rows]


def _audit_path(capture_id=None):
    directory = Path(__file__).resolve().parents[2] / "audit" / "signaling-materialized"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = capture_id or "all"
    return directory / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{suffix}.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--capture-id")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if len(args.reason.strip()) < 10:
        print("VERDICT=FAIL reason=reason_too_short", file=sys.stderr)
        return 2
    if not guard_bc3_deploy_lock(action="backfill_signaling_materialized"):
        return 1
    # Same project-scoped session lock as populate_chain: backfill and import
    # finalization can never publish competing generations.
    lock_key = f"populate:{args.project_id}"
    report = None
    try:
        with engine.connect() as lock:
            acquired = bool(lock.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                {"key": lock_key},
            ).scalar())
            lock.commit()
            if not acquired:
                print("VERDICT=FAIL reason=project_lock_busy", file=sys.stderr)
                return 3
            try:
                with SessionLocal() as db:
                    before = _snapshot(db, args.project_id, args.capture_id)
                    if not before:
                        print("VERDICT=FAIL reason=capture_not_found", file=sys.stderr)
                        return 4
                    result = materialize_project(
                        db, args.project_id, capture_id=args.capture_id,
                    )
                    after = _snapshot(db, args.project_id, args.capture_id)
                    report = dict(
                        op_id=uuid4().hex,
                        when=datetime.now(timezone.utc).isoformat(),
                        project_id=args.project_id,
                        capture_id=args.capture_id,
                        reason=args.reason,
                        source="existing_database_tables_no_decode",
                        before=before, after=after, result=result,
                    )
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),
                             {"key": lock_key})
                lock.commit()
    except Exception as exc:
        print(f"VERDICT=FAIL reason={exc!r}", file=sys.stderr)
        return 1
    audit = _audit_path(args.capture_id)
    audit.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"VERDICT=PASS audit={audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
