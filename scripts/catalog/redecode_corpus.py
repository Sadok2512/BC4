"""Phase 2.2c — Re-decode des 94 captures corpus avec decoder 1.6.0.

Rejoue l'ingest (ingest_upload) pour chaque capture déjà en base,
depuis le fichier source `nmf_file.source_path`. Les tables Light/Deep/
Raw sont purgées capture-par-capture avant re-decode.

Logs :
  /app/exports/redecode_progress.txt       — ligne par capture (statut)
  /app/exports/redecode_<ts>.log           — stdout/stderr principal

Usage inside bc4-api-1 :
  docker exec -w /app bc4-api-1 bash -c \
    "nohup python -u scripts/catalog/redecode_corpus.py > /app/exports/redecode_$(date +%Y%m%d_%H%M%S).log 2>&1 &"
"""
import sys, time, traceback
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import text
from app.db import SessionLocal
from app.models import Project
from app.nmf_decoder.store import decode_capture
from app.nmf_decoder import DECODER_VERSION

PROGRESS = Path("/app/exports/redecode_progress.txt")
PROGRESS.parent.mkdir(parents=True, exist_ok=True)

def log_line(s: str):
    now = time.strftime("%H:%M:%S")
    with PROGRESS.open("a") as f: f.write(f"[{now}] {s}\n")
    print(f"[{now}] {s}", flush=True)

def purge_capture(db, pid: str, cap: str):
    """Supprime UNIQUEMENT les tables light/group/deep/cell_second.

    BC3 arbitrage 10e passe : le replay ne touche PAS stg_event ni
    stg_event_raw ni param_occurrence (dictionnaire BC1 préservé). Le
    cascade stg_event → param_occurrence (FK ON DELETE CASCADE, 1.25M
    lignes, sans index support jusqu'à 0051) coûtait ~14 min par
    capture + effaçait les observations du dict. nmf_capture reste
    (UPSERT par ingest_upload via ON CONFLICT).
    """
    for tbl in ("nmf_cell_second", "nmf_event_light", "nmf_event_light_ext",
                "nmf_event_group", "nmf_event_deep"):
        try:
            db.execute(text(f"DELETE FROM {tbl} WHERE project_id=:p AND capture_id=:c"),
                       {"p": pid, "c": cap})
        except Exception as e:
            log_line(f"  purge WARN {tbl}: {e!r}")
    db.commit()

def main():
    """BC3 10e passe : utilise decode_capture (replay-only, lit source via
    nmf_file.source_path, NE TOUCHE PAS stg_event ni stg_event_raw ni
    param_occurrence). Les tables Light/Group/Deep sont purgées puis
    re-remplies ; nmf_capture est UPSERT."""
    args = sys.argv[1:]
    only_cap = None
    kind_filter = None
    if args and args[0] == "--one":
        only_cap = args[1] if len(args) > 1 else None
    elif args and args[0] == "--kind":
        kind_filter = args[1] if len(args) > 1 else None
    db = SessionLocal()
    try:
        log_line(f"START decoder={DECODER_VERSION} replay-only (no stg_* touch) kind_filter={kind_filter}")
        rows = db.execute(text("""
            SELECT c.project_id, c.capture_id, c.decoder_version, c.decode_level, f.source_path, c.kind
            FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
            ORDER BY c.project_id, c.capture_id
        """)).all()
        if only_cap:
            rows = [r for r in rows if r[1] == only_cap]
        if kind_filter:
            rows = [r for r in rows if r[5] == kind_filter]
        # 1.7.0 — Priorité aux témoins (PNG + gardes) : 723547b196b3 NR,
        # 44621571bccc LTE. Le reste du corpus suit en nohup.
        PRIORITY = ['723547b196b3', '44621571bccc']
        rows = sorted(rows, key=lambda r: (PRIORITY.index(r[1]) if r[1] in PRIORITY else 1000, r[0], r[1]))
        total = len(rows)
        log_line(f"captures to redecode: {total}")
        done = 0; failed = []
        for pid, cap, old_ver, old_level, source_path, kind in rows:
            t0 = time.time()
            if not source_path or not Path(source_path).exists():
                log_line(f"[{done+1}/{total}] {pid}/{cap} SKIP source_missing={source_path}")
                done += 1
                continue
            try:
                purge_capture(db, pid, cap)
                level = old_level if old_level in ("light", "deep") else "light"
                result = decode_capture(db, pid, cap, level, force=True)
                db.commit()
                dt = time.time() - t0
                log_line(f"[{done+1}/{total}] {pid}/{cap} OK level={level} n_rec={result.get('n_records')} prev={old_ver} elapsed={dt:.1f}s")
            except Exception as exc:
                db.rollback()
                log_line(f"[{done+1}/{total}] {pid}/{cap} FAIL {type(exc).__name__}: {str(exc)[:200]}")
                failed.append((pid, cap, str(exc)))
            done += 1
        log_line(f"DONE total={total} failed={len(failed)}")
        if failed:
            for pid, cap, err in failed[:20]:
                log_line(f"  FAIL {pid}/{cap} : {err[:120]}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
