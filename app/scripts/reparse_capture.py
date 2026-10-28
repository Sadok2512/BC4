"""Re-parse EXPLICITE d'une capture — seul chemin autorisé après 2026-10-28.

Le snapshot de capture (`nmf_capture.decoder_version`,
`decode_level`, `binning_mode`, …) est immuable par défaut : ni la
reprise d'un job (`requeue_import_*`), ni la finalisation
(`populate_chain` / `ensure_light`), ni une mise à jour du décodeur
(`DECODER_VERSION` bumpé en code) ne doivent re-décoder une capture
déjà `done`.

Cette commande applicative est le SEUL endroit où `decode_capture()`
est appelé avec `force=True`. Avant/après : les 6 colonnes de snapshot
+ `n_records` + `n_partial` sont imprimés et tracés dans
`audit/reparse/<timestamp>_<capture_id>.json`.

Usage :
  python -m app.scripts.reparse_capture <project_id> <capture_id> \\
    [--level deep|light] [--reason "..."]

Discipline :
  - advisory lock worker (comme les requeue_*) : refuse si worker actif ;
  - impose `--reason` (justification tracée dans le journal) ;
  - rollback si decode_capture lève, trace du refus.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.nmf_decoder.store import decode_capture
from app.services.import_worker import LOCK_ID


SNAPSHOT_COLS = (
    "decode_level", "decoder_version", "schema_version", "format_version",
    "binning_mode", "temporal_resolution", "spatial_bin_m",
    "aggregation_contract_version", "n_records", "n_partial",
)


def _snapshot(db, pid: str, cap: str) -> dict | None:
    row = db.execute(text(f"""
        SELECT project_id, capture_id, {', '.join(SNAPSHOT_COLS)}
        FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap
    """), {"pid": pid, "cap": cap}).mappings().first()
    return dict(row) if row else None


def _audit_dir() -> Path:
    base = Path(__file__).resolve().parents[2] / "audit" / "reparse"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-parse explicite d'une capture (force=True).")
    ap.add_argument("project_id")
    ap.add_argument("capture_id")
    ap.add_argument("--level", choices=("deep", "light"), default="deep")
    ap.add_argument("--reason", required=True,
                    help="Justification obligatoire tracée dans le journal.")
    args = ap.parse_args()

    with engine.connect() as lock:
        acquired = bool(
            lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID}).scalar()
        )
        lock.commit()
        if not acquired:
            print("REFUSE: import worker is active — stop it before reparse", file=sys.stderr)
            return 1
        try:
            with SessionLocal() as db:
                before = _snapshot(db, args.project_id, args.capture_id)
                if before is None:
                    print(f"FAIL: capture ({args.project_id}, {args.capture_id}) introuvable",
                          file=sys.stderr)
                    return 2

                print("BEFORE snapshot:")
                for k, v in before.items():
                    print(f"  {k} = {v!r}")

                # force=True : contourne le skip immuable (seul usage légitime).
                result = decode_capture(db, args.project_id, args.capture_id,
                                        args.level, force=True)
                db.commit()

                after = _snapshot(db, args.project_id, args.capture_id)
                print("\nAFTER snapshot:")
                for k, v in after.items():
                    print(f"  {k} = {v!r}")
                print(f"\ndecode result: {result}")

                audit = _audit_dir() / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{args.capture_id}.json"
                audit.write_text(json.dumps({
                    "op_id": uuid.uuid4().hex,
                    "when": datetime.now(timezone.utc).isoformat(),
                    "project_id": args.project_id,
                    "capture_id": args.capture_id,
                    "level": args.level,
                    "reason": args.reason,
                    "before": before,
                    "after": after,
                    "result": result,
                }, indent=2, default=str))
                print(f"\naudit → {audit}")
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
            lock.commit()

    print("\nOK — reparse applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
