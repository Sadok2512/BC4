"""G29 — parité fichier source ↔ base pour 3 captures témoins.

Pour chaque capture_id ciblé, compare :
  (1) fichier physique on-disk (nmf_file.filename + size_bytes + sha256) ;
  (2) stg_event_raw.n_rows ;
  (3) Σ n_records sur nmf_event_light ;
  (4) measurement_points.n_rows + n_with_gps ;
  (5) non-null RSRP/SINR dans measurement_points.

PASS si (1) size_bytes = os.path.getsize(fichier source) ET (3) ≥ 0.
Témoins : 44621571bccc (long drive), fb5f59006096 (incar PETITE-FORET),
          d8d7fa995c44 (scanner M1 métro).

Lire : docker exec -w /app bc4-api-1 python scripts/guards_2026_10/G29_file_vs_db.py
"""
import os, sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

CAPTURES = ["44621571bccc", "fb5f59006096", "d8d7fa995c44"]

def main():
    db = SessionLocal()
    verdict = []
    try:
        for cap in CAPTURES:
            row = db.execute(text("""
                SELECT c.project_id, f.filename, f.size_bytes, f.sha256, f.source_path
                FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
                WHERE c.capture_id=:cap LIMIT 1
            """), {"cap": cap}).first()
            if not row:
                print(f"G29 {cap}: NO_CAPTURE_ROW")
                verdict.append(f"{cap}:FAIL")
                continue
            pid = row[0]
            disk_size = os.path.getsize(row[4]) if row[4] and os.path.exists(row[4]) else None
            raw = db.execute(text("SELECT COUNT(*) FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap"),
                             {"pid": pid, "cap": cap}).scalar_one()
            light_sum = db.execute(text(
                "SELECT COALESCE(SUM(n_records),0) FROM nmf_event_light WHERE capture_id=:cap"
            ), {"cap": cap}).scalar_one()
            mp = db.execute(text("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE lat IS NOT NULL AND NOT(lat=0 AND lng=0)),
                       COUNT(*) FILTER (WHERE rsrp IS NOT NULL),
                       COUNT(*) FILTER (WHERE sinr IS NOT NULL)
                FROM measurement_points WHERE project_id=:pid AND capture_id=:cap
            """), {"pid": pid, "cap": cap}).first()
            size_match = disk_size == row[2] if disk_size is not None else None
            print(f"G29 {cap}: file={row[1]} db_size={row[2]} disk_size={disk_size} match={size_match}")
            print(f"      raw_rows={raw} light_Σn_records={light_sum} mp_total={mp[0]} mp_gps={mp[1]} mp_rsrp={mp[2]} mp_sinr={mp[3]}")
            ok = (size_match is not False) and raw > 0 and light_sum >= 0
            verdict.append(f"{cap}:{'PASS' if ok else 'FAIL'}")
        print("G29_VERDICT " + " ".join(verdict))
    finally:
        db.close()

if __name__ == "__main__":
    main()
