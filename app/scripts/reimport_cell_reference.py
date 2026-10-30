"""Reimport a cell-reference CSV under the BC3 deployment lock.

Usage:
  python -m app.scripts.reimport_cell_reference /path/ref_cell_4G5G.csv \
    --reason "separate band MHz from exact LTE/NR channels"

The operation is idempotent on ``cell_ref.id`` and does not decode NMF data.
It writes the normal ``reference_import`` history row plus a JSON operational
audit containing the source checksum, reason and before/after column counts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import text

from app.scripts.deploy_guard import guard_bc3_deploy_lock
from app.services.cell_ref_ingest import MAX_BODY_BYTES, ingest_csv_stream


def _snapshot(db) -> dict[str, int]:
    row = db.execute(text("""
        SELECT COUNT(*)::bigint AS total,
               COUNT(band_mhz)::bigint AS band_mhz,
               COUNT(earfcn)::bigint AS earfcn,
               COUNT(nr_arfcn)::bigint AS nr_arfcn
        FROM cell_ref
    """)).mappings().one()
    return {key: int(value) for key, value in row.items()}


def _audit_path() -> Path:
    directory = Path(__file__).resolve().parents[2] / "audit" / "cell-ref-channel-reimport"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{stamp}-{uuid4().hex[:8]}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    reason = args.reason.strip()
    if len(reason) < 10:
        print("VERDICT=FAIL reason=reason_too_short", file=sys.stderr)
        return 2
    if not guard_bc3_deploy_lock(action="reimport_cell_reference"):
        return 1
    try:
        source = args.source.resolve(strict=True)
        size = source.stat().st_size
    except OSError as exc:
        print(f"VERDICT=FAIL reason=source_unreadable detail={exc}", file=sys.stderr)
        return 2
    if not source.is_file() or size > MAX_BODY_BYTES:
        print(
            f"VERDICT=FAIL reason=source_size_invalid bytes={size} max_bytes={MAX_BODY_BYTES}",
            file=sys.stderr,
        )
        return 2

    from app.db import SessionLocal, engine

    try:
        with engine.connect() as lock:
            acquired = bool(lock.execute(text(
                "SELECT pg_try_advisory_lock(hashtext('cell_ref:reimport'))"
            )).scalar())
            lock.commit()
            if not acquired:
                print("VERDICT=FAIL reason=cell_ref_reimport_busy", file=sys.stderr)
                return 3
            try:
                with SessionLocal() as db, source.open("rb") as stream:
                    before = _snapshot(db)
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    stream.seek(0)
                    report = ingest_csv_stream(
                        db,
                        stream,
                        filename=source.name,
                        actor="BC3 guarded reimport",
                    )
                    after = _snapshot(db)
            finally:
                lock.execute(text(
                    "SELECT pg_advisory_unlock(hashtext('cell_ref:reimport'))"
                ))
                lock.commit()
    except Exception as exc:
        print(f"VERDICT=FAIL reason=reimport_failed detail={exc!r}", file=sys.stderr)
        return 1

    audit = {
        "op_id": uuid4().hex,
        "when": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "source": str(source),
        "source_bytes": size,
        "source_sha256": digest,
        "before": before,
        "after": after,
        "import_report": report.model_dump(),
    }
    path = _audit_path()
    path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))
    print(f"VERDICT=PASS audit={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
