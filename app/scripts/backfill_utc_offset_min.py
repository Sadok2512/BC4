"""Backfill `nmf_file.utc_offset_min` depuis les fichiers source déjà en base.

Lit `#UT` col 1 (NFF 2.19 "UTC_to_local", minutes, signe local-UTC) via
`app.ingest.nmf._extract_utc_offset_min` — zero data fabriquée : si
`source_path` manquant OU fichier illisible OU en-tête `#UT` absent,
reste `NULL` avec motif reporté en sortie.

Usage
-----
    docker exec bc4-api-1 python -m app.scripts.backfill_utc_offset_min [--dry-run] [--force]

Options
-------
--dry-run : affiche uniquement le plan, pas d'UPDATE.
--force   : écrase les valeurs non-NULL existantes.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingest.nmf import _extract_utc_offset_min
from app.models import NmfFile

LOG = logging.getLogger("backfill_utc_offset_min")


def run(dry_run: bool = False, force: bool = False) -> int:
    db: Session = SessionLocal()
    try:
        q = select(NmfFile.id, NmfFile.filename, NmfFile.source_path, NmfFile.utc_offset_min)
        rows = list(db.execute(q))
        total = len(rows)
        reasons = {"ok": 0, "already_set": 0, "no_source_path": 0, "file_missing": 0, "no_header": 0}
        updates: list[tuple[str, int]] = []
        for file_id, filename, source_path, existing in rows:
            if existing is not None and not force:
                reasons["already_set"] += 1
                continue
            if not source_path:
                reasons["no_source_path"] += 1
                print(f"[WARN] {file_id} ({filename}) : no_source_path")
                continue
            if not os.path.isfile(source_path):
                reasons["file_missing"] += 1
                print(f"[WARN] {file_id} ({filename}) : file_missing path={source_path}")
                continue
            value = _extract_utc_offset_min(source_path)
            if value is None:
                reasons["no_header"] += 1
                print(f"[WARN] {file_id} ({filename}) : no_header")
                continue
            reasons["ok"] += 1
            updates.append((file_id, value))
            print(f"[OK]   {file_id} ({filename}) : utc_offset_min={value}")
        print(f"\n--- SUMMARY ---\ntotal={total}  ok={reasons['ok']}  "
              f"already_set={reasons['already_set']}  no_source_path={reasons['no_source_path']}  "
              f"file_missing={reasons['file_missing']}  no_header={reasons['no_header']}")
        if dry_run:
            print("[DRY-RUN] no UPDATE performed")
            return 0
        for file_id, value in updates:
            db.execute(update(NmfFile).where(NmfFile.id == file_id).values(utc_offset_min=value))
        db.commit()
        print(f"[DONE] {len(updates)} rows updated")
        return 0
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite non-NULL values")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
