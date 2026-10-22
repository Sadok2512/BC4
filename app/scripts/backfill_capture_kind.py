"""Backfill `nmf_capture.kind` ('ue' | 'scanner' | NULL) depuis les event_codes
observés dans `nmf_event_light`.

Classification identique à `app.nmf_decoder.store.classify_capture_kind` :
- 'scanner' = events SCAN* (CELLSCAN|OFDMSCAN|SCANCONFIG|STARTSCAN) présents
   ET aucun event cell-scoped UE (CELLMEAS|CI).
- 'ue'      = CELLMEAS ou CI présent.
- NULL      = ni l'un ni l'autre (très rare — write explicitement NULL).

Jamais depuis le nom de fichier.

Usage
-----
    docker exec bc4-api-1 python -m app.scripts.backfill_capture_kind [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.nmf_decoder.store import classify_capture_kind

LOG = logging.getLogger("backfill_capture_kind")


def run(dry_run: bool = False, force: bool = False) -> int:
    db: Session = SessionLocal()
    try:
        caps = list(
            db.execute(
                text("SELECT project_id, capture_id, kind FROM nmf_capture ORDER BY decoded_at")
            )
        )
        updates: list[tuple[str, str, str | None]] = []
        stats = {"ue": 0, "scanner": 0, "null": 0, "already": 0}
        for pid, cap, existing in caps:
            if existing is not None and not force:
                stats["already"] += 1
                continue
            kind = classify_capture_kind(db, pid, cap)
            stats[kind if kind is not None else "null"] += 1
            updates.append((pid, cap, kind))
            print(f"[{kind or 'NULL':>7}]  {pid} / {cap}")
        print(
            f"\n--- SUMMARY ---\ntotal={len(caps)}  ue={stats['ue']}  "
            f"scanner={stats['scanner']}  null={stats['null']}  already_set={stats['already']}"
        )
        if dry_run:
            print("[DRY-RUN] no UPDATE performed")
            return 0
        for pid, cap, kind in updates:
            db.execute(
                text(
                    "UPDATE nmf_capture SET kind=:kind "
                    "WHERE project_id=:pid AND capture_id=:cap"
                ),
                {"pid": pid, "cap": cap, "kind": kind},
            )
        db.commit()
        print(f"[DONE] {len(updates)} rows updated")
        return 0
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing values")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
