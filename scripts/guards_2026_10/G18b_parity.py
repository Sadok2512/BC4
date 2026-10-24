"""G18b — parité stg_event vs stg_event_raw pour les captures restaurées.
stg_event est dérivé de stg_event_raw (projection filtrée sur messages
L3/RRC/SIP). Pour une capture donnée, |stg_event| ≤ |stg_event_raw|.
PASS = inégalité respectée ∀ capture ; FAIL = fuite ou perte.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT c.project_id, c.capture_id,
                   (SELECT COUNT(*) FROM stg_event_raw r WHERE r.project_id=c.project_id AND r.capture_id=c.capture_id) AS raw,
                   (SELECT COUNT(*) FROM stg_event     e WHERE e.project_id=c.project_id AND e.capture_id=c.capture_id) AS proj
            FROM nmf_capture c
            ORDER BY c.project_id, c.capture_id
        """)).all()
        bad = [(r[0], r[1], r[2], r[3]) for r in rows if r[3] > r[2]]
        print(f"G18b total_pairs={len(rows)} parity_violations={len(bad)}")
        for pid, cap, raw, proj in bad[:10]:
            print(f"  LEAK pid={pid} cap={cap} raw={raw} proj={proj}")
        verdict = "PASS" if not bad else "FAIL"
        print(f"G18b_VERDICT {verdict}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
