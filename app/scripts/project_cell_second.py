"""
0.74.10 — Backfill idempotent de la projection nmf_cell_second.

Historique : la projection cell_second (lignes 56-58 de app/nmf_decoder/
store.py:write_light) a été ajoutée dans le décodeur à partir de la
version 1.3.0. Toutes les captures décodées avant cet ajout
(decode 1.0.0 Light) ont nmf_cell_second = 0 row et donc une table
Metrics vide (ex. capture 44621571bccc du 2026-10-19).

Fix : CLI qui relance decode_capture(..., force=True) sur chaque
capture ciblée. On réutilise exactement le même code path que
POST /decode — jamais de SQL one-shot, jamais de reconstruction
hors du décodeur authoritative.

Usage :
  docker exec bc4-api-1 python -m app.scripts.project_cell_second --capture 44621571bccc
  docker exec bc4-api-1 python -m app.scripts.project_cell_second --missing
  docker exec bc4-api-1 python -m app.scripts.project_cell_second --missing --dry-run

Idempotence garantie :
  - decode_capture() DELETE puis INSERT dans nmf_event_light et nmf_cell_second
  - Rejouer la commande sur une capture déjà OK = no-op (DELETE + réinsert
    des mêmes lignes, status ok)
  - Un lock advisory par projet évite les concurrents

Garde G20 (à exécuter avant/après) :
  SELECT count(*) FROM nmf_capture c
   WHERE c.decode_level IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM nmf_cell_second s WHERE s.capture_id=c.capture_id);
"""
from __future__ import annotations
import argparse
import sys
import time
from sqlalchemy import text

from app.db import SessionLocal
from app.nmf_decoder.store import decode_capture
from app.scripts.deploy_guard import guard_bc3_deploy_lock


def missing_captures(db) -> list[tuple[str, str, str]]:
    """Retourne [(project_id, capture_id, decode_level)] pour chaque capture
    décodée sans aucune ligne nmf_cell_second."""
    sql = """
        SELECT c.project_id, c.capture_id, c.decode_level
        FROM nmf_capture c
        WHERE c.decode_level IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM nmf_cell_second s
            WHERE s.project_id = c.project_id AND s.capture_id = c.capture_id
          )
        ORDER BY c.decoded_at
    """
    return [(r.project_id, r.capture_id, r.decode_level) for r in db.execute(text(sql))]


def project_capture(db, project_id: str, capture_id: str, level: str, dry_run: bool = False) -> dict:
    """Relance decode_capture(force=True) pour reconstruire nmf_cell_second.
    Même code path que POST /decode."""
    if dry_run:
        return dict(project_id=project_id, capture_id=capture_id, level=level, action="DRY_RUN")
    t0 = time.perf_counter()
    try:
        result = decode_capture(db, project_id, capture_id, level, force=True)
        db.commit()
        cell_rows = db.execute(
            text("SELECT count(*) FROM nmf_cell_second WHERE project_id=:p AND capture_id=:c"),
            {"p": project_id, "c": capture_id},
        ).scalar_one()
        return dict(
            project_id=project_id,
            capture_id=capture_id,
            level=level,
            cell_second_rows=cell_rows,
            elapsed_s=time.perf_counter() - t0,
            action="REDECODED",
            **({"n_records": result["n_records"]} if "n_records" in result else {}),
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return dict(
            project_id=project_id,
            capture_id=capture_id,
            level=level,
            action="ERROR",
            error=type(e).__name__ + ": " + str(e),
            elapsed_s=time.perf_counter() - t0,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="project_cell_second")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture", help="capture_id précis à backfiller")
    group.add_argument("--missing", action="store_true", help="toutes les captures sans cell_second")
    p.add_argument("--project", help="requis avec --capture (sinon dérivé de la DB)")
    p.add_argument("--dry-run", action="store_true", help="liste les captures ciblées sans décoder")
    args = p.parse_args(argv)

    if not args.dry_run and not guard_bc3_deploy_lock(action="project_cell_second"):
        return 1

    db = SessionLocal()
    try:
        if args.capture:
            row = db.execute(
                text("SELECT project_id, decode_level FROM nmf_capture WHERE capture_id=:c"),
                {"c": args.capture},
            ).mappings().first()
            if not row:
                print(f"ERROR: capture {args.capture} not found in nmf_capture", file=sys.stderr)
                return 2
            if args.project and args.project != row["project_id"]:
                print(f"ERROR: --project={args.project} ne correspond pas au project_id DB ({row['project_id']})", file=sys.stderr)
                return 2
            captures = [(row["project_id"], args.capture, row["decode_level"])]
        else:
            captures = missing_captures(db)

        print(f"targets: {len(captures)}")
        if args.dry_run:
            for pid, cap, lvl in captures[:20]:
                print(f"  DRY_RUN project={pid} capture={cap} level={lvl}")
            if len(captures) > 20:
                print(f"  ... + {len(captures) - 20} autres")
            return 0

        ok = failed = 0
        for pid, cap, lvl in captures:
            res = project_capture(db, pid, cap, lvl, dry_run=False)
            tag = "OK" if res["action"] == "REDECODED" and res.get("cell_second_rows", 0) >= 0 else "FAIL"
            if tag == "OK":
                ok += 1
            else:
                failed += 1
            print(
                f"  [{tag}] project={res['project_id']} capture={res['capture_id']} "
                f"level={res['level']} rows={res.get('cell_second_rows','?')} "
                f"elapsed={res.get('elapsed_s',0):.2f}s "
                + (f"error={res.get('error')}" if res["action"] == "ERROR" else "")
            )
        print(f"summary: ok={ok} failed={failed}")
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
