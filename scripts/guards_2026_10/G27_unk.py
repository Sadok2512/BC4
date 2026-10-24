"""G27 — events avec champs `unknown[]` non alloués : dette décodeur.

Pour chaque event_code présent dans nmf_event_light avec unknown[] non vide,
agrège : nb lignes avec unknown, nb distinct de noms de champs non alloués,
noms des 3 premiers champs (preuve).

Verdict : FAIL conservé = dette à combler côté décodeur (schémas YAML).
Pas de "ok" allowlist : TOUT champ non alloué est une dette, listée telle quelle.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            WITH exploded AS (
              SELECT event_code, u AS field
              FROM nmf_event_light,
                   LATERAL unnest(unknown) AS u
              WHERE unknown IS NOT NULL AND array_length(unknown, 1) > 0
            )
            SELECT event_code,
                   COUNT(*) AS n_rows,
                   COUNT(DISTINCT field) AS n_fields,
                   string_agg(DISTINCT field, ',' ORDER BY field) AS sample
            FROM exploded GROUP BY event_code ORDER BY n_fields DESC, n_rows DESC
        """)).all()
        print(f"G27 events_with_unknown={len(rows)}")
        print(f"{'event_code':<16} {'n_rows':>8} {'n_fields':>9}  sample_fields")
        total_rows = 0
        total_fields = 0
        for r in rows:
            total_rows += int(r[1]); total_fields += int(r[2])
            sample = (r[3][:80] + "…") if r[3] and len(r[3]) > 80 else (r[3] or "")
            print(f"{r[0]:<16} {int(r[1]):>8} {int(r[2]):>9}  {sample}")
        verdict = "FAIL" if rows else "PASS"
        print(f"G27_VERDICT {verdict} total_events={len(rows)} total_rows_with_unknown={total_rows} total_distinct_fields={total_fields}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
