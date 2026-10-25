"""G20 — events SCAN* ne doivent exister QUE sur captures `kind='scanner'`.

Règle BC3 : les events SCANCONFIG, STARTSCAN, CELLSCAN, OFDMSCAN sont
spécifiques au mode Ibflex-Scanner Nemo HANDY. Toute occurrence sur une
capture `kind='ue'` ou `null` = fuite de classification.

PASS = `COUNT(*) = 0` sur stg_event_raw où event_code SCAN* ET
capture_id n'est pas kind='scanner'.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

SCAN_CODES = ("SCANCONFIG", "STARTSCAN", "CELLSCAN", "OFDMSCAN")

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(f"""
            SELECT c.capture_id, c.kind, r.event_code, COUNT(*) AS n
            FROM stg_event_raw r
            JOIN nmf_capture c ON c.project_id=r.project_id AND c.capture_id=r.capture_id
            WHERE r.event_code IN ({','.join(f"'{c}'" for c in SCAN_CODES)})
              AND (c.kind IS NULL OR c.kind != 'scanner')
            GROUP BY c.capture_id, c.kind, r.event_code
            ORDER BY n DESC
        """)).all()
        leaks = len(rows)
        print(f"G20 scan_events_on_non_scanner_captures={leaks}")
        for r in rows[:20]:
            print(f"  LEAK cap={r[0]} kind={r[1]!r} event={r[2]} n={r[3]}")
        total_scan = db.execute(text(
            f"SELECT COUNT(*) FROM stg_event_raw WHERE event_code IN ({','.join(f'''{repr(c)}''' for c in SCAN_CODES)})"
        )).scalar_one()
        print(f"G20 total_scan_events_in_corpus={total_scan}")
        verdict = "PASS" if leaks == 0 else "FAIL"
        print(f"G20_VERDICT {verdict} leaks={leaks}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
