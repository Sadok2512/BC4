"""G26 — offsets temporels nmf_start_at ↔ utc_offset_min.

Chaque capture doit avoir un `nmf_file.start_at` (verbatim NFF #START) et
`nmf_file.ts_label`-adjacent `utc_offset_min` numérique.

PASS = toute capture a start_at != NULL ET utc_offset_min ∈ [-720, 840]
(validité TZ). FAIL = sinon.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT f.id, f.filename, f.start_at, f.utc_offset_min
            FROM nmf_file f
            WHERE EXISTS (SELECT 1 FROM nmf_capture c WHERE c.nmf_file_id=f.id)
            ORDER BY f.filename
        """)).all()
        total = len(rows)
        missing_start = sum(1 for r in rows if not r[2])
        bad_offset = sum(1 for r in rows if r[3] is None or r[3] < -720 or r[3] > 840)
        print(f"G26 files_total={total} missing_start={missing_start} bad_offset={bad_offset}")
        for r in rows:
            if not r[2] or r[3] is None or r[3] < -720 or r[3] > 840:
                print(f"  WARN {r[1][:60]} start_at={r[2]} offset={r[3]}")
        verdict = "PASS" if (missing_start == 0 and bad_offset == 0) else "FAIL"
        print(f"G26_VERDICT {verdict} total={total}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
