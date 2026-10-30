"""Invalidate the persisted Metrics catalogue cache under the BC3 deploy lock.

The operation is deliberately global: a catalogue release is global too.  It is
safe to replay; an already empty cache produces ``deleted=0`` and PASS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import text

from app.db import SessionLocal
from app.scripts.deploy_guard import guard_bc3_deploy_lock


def _rebuild_project_cache(db, project_id: str) -> None:
    """Warm one v4 row so fail-closed parity guards keep a witness."""
    from app.kpi.catalog_release.registry import current_catalog
    from app.kpi.metrics_catalog_v4 import build_catalog_v4

    current = current_catalog(db)
    if current is None:
        raise RuntimeError("cannot rebuild catalogue cache without an active release")
    decode_stamp = db.execute(text("""
        SELECT md5(coalesce(string_agg(
          capture_id || ':' || decoder_version || ':' || coalesce(decoded_at::text,''),
          ',' ORDER BY capture_id),''))
        FROM nmf_capture WHERE project_id=:pid
    """), {"pid": project_id}).scalar_one()
    identity_stamp = db.execute(text("""
        SELECT md5(count(*)::text || ':' || coalesce(max(built_at)::text,''))
        FROM nmf_cell_identity WHERE project_id=:pid
    """), {"pid": project_id}).scalar_one()
    stamp = f"{decode_stamp}|identity={identity_stamp}|cat={current.version}"
    payload = build_catalog_v4(db, project_id, current)
    db.execute(text("""
        INSERT INTO metrics_catalog_cache(project_id,decode_stamp,payload)
        VALUES(:pid,:stamp,CAST(:payload AS jsonb))
        ON CONFLICT(project_id) DO UPDATE SET decode_stamp=excluded.decode_stamp,
          payload=excluded.payload,updated_at=now()
    """), {"pid": project_id, "stamp": stamp, "payload": json.dumps(payload)})


def invalidate_catalog_cache(db, *, reason: str, source: str) -> dict:
    """Delete and rebuild cache witnesses in the caller transaction."""
    project_ids = list(db.execute(text(
        "SELECT project_id FROM metrics_catalog_cache ORDER BY project_id"
    )).scalars())
    before = int(db.execute(text("SELECT count(*) FROM metrics_catalog_cache")).scalar_one())
    result = db.execute(text("DELETE FROM metrics_catalog_cache"))
    for project_id in project_ids:
        _rebuild_project_cache(db, project_id)
    after = int(db.execute(text("SELECT count(*) FROM metrics_catalog_cache")).scalar_one())
    return {
        "op_id": uuid4().hex,
        "when": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "source": source,
        "rows_before": before,
        "rows_deleted": int(result.rowcount or 0),
        "rows_rebuilt": len(project_ids),
        "rows_after": after,
        "project_ids": project_ids,
        "idempotent": after == len(project_ids),
    }


def write_audit(report: dict) -> Path:
    directory = Path(__file__).resolve().parents[2] / "audit" / "catalog-cache-invalidation"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{timestamp}_{report['op_id']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if not args.reason.strip():
        print("VERDICT=FAIL reason=empty_reason", file=sys.stderr)
        return 2
    if not guard_bc3_deploy_lock(action="catalog_cache.invalidate"):
        return 1

    try:
        with SessionLocal() as db:
            report = invalidate_catalog_cache(
                db, reason=args.reason.strip(), source="manual_command"
            )
            db.commit()
        audit = write_audit(report)
    except Exception as exc:
        print(f"VERDICT=FAIL reason=cache_invalidation_error detail={exc!r}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True))
    print(f"VERDICT=PASS audit={audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
