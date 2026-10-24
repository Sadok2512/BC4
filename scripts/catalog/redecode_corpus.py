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
from app.ingest.nmf import ingest_upload, resolve_decoder
from app.nmf_decoder import DECODER_VERSION

PROGRESS = Path("/app/exports/redecode_progress.txt")
PROGRESS.parent.mkdir(parents=True, exist_ok=True)

def log_line(s: str):
    now = time.strftime("%H:%M:%S")
    with PROGRESS.open("a") as f: f.write(f"[{now}] {s}\n")
    print(f"[{now}] {s}", flush=True)

def purge_capture(db, pid: str, cap: str):
    """Supprime toutes les traces d'une capture pour re-ingest clean."""
    for tbl, where in [
        ("nmf_cell_second", "project_id=:p AND capture_id=:c"),
        ("nmf_event_light", "project_id=:p AND capture_id=:c"),
        ("nmf_event_light_ext", "project_id=:p AND capture_id=:c"),
        ("nmf_event_group", "project_id=:p AND capture_id=:c"),
        ("stg_event", "project_id=:p AND capture_id=:c"),
        ("stg_event_raw", "project_id=:p AND capture_id=:c"),
        ("nmf_capture", "project_id=:p AND capture_id=:c"),
    ]:
        try:
            db.execute(text(f"DELETE FROM {tbl} WHERE {where}"), {"p": pid, "c": cap})
        except Exception as e:
            log_line(f"  purge WARN {tbl}: {e!r}")
    db.commit()

def main():
    db = SessionLocal()
    try:
        handle = resolve_decoder()
        log_line(f"START decoder={DECODER_VERSION} underlying={handle.version if handle.available else 'N/A'}")
        # Scope corpus = tous les (project, capture) existants
        rows = db.execute(text("""
            SELECT c.project_id, c.capture_id, c.nmf_file_id, f.filename, f.source_path
            FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
            ORDER BY c.project_id, c.capture_id
        """)).all()
        total = len(rows)
        log_line(f"captures to redecode: {total}")
        done = 0; failed = []
        for pid, cap, nmf_file_id, filename, source_path in rows:
            t0 = time.time()
            project = db.get(Project, pid)
            if not project:
                log_line(f"[{done+1}/{total}] {pid}/{cap} SKIP project_not_found")
                continue
            if not source_path or not Path(source_path).exists():
                log_line(f"[{done+1}/{total}] {pid}/{cap} SKIP source_missing={source_path}")
                continue
            try:
                purge_capture(db, pid, cap)
                with open(source_path, "rb") as stream:
                    nmf = ingest_upload(db, project, stream, filename, handle, populate=False)
                db.commit()
                dt = time.time() - t0
                log_line(f"[{done+1}/{total}] {pid}/{cap} OK n_rec={nmf.n_records} n_cap={nmf.n_captures} elapsed={dt:.1f}s")
            except Exception as exc:
                db.rollback()
                log_line(f"[{done+1}/{total}] {pid}/{cap} FAIL {exc!r}")
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
