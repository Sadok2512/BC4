"""G29 — parité PAR event_code pour 3 captures témoins.

Pour chaque capture_id, tableau PAR event_code avec 5 colonnes :
  (1) lignes_fichier   = COUNT depuis stg_event_raw (events décodés du
      fichier source avant toute projection)
  (2) stg_event        = COUNT dans stg_event (projection filtrée L3/RRC/SIP)
  (3) light_Σn_records = SUM(nmf_event_light.n_records) GROUP BY event_code
  (4) light_doc_nonnull= COUNT nmf_event_light avec ≥1 champ documenté
      non-NULL (ni unknown[] ni reasons[]) GROUP BY event_code
  (5) measurement_pts  = COUNT measurement_points GROUP BY event_code

Témoins : 44621571bccc (parcours long), fb5f59006096 (incar), un autre
parcours_* 723547b196b3 (le plus gros fix GPS).
Toute cellule en écart avec les 4 autres → ligne brute à côté.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text, inspect
from app.db import SessionLocal

CAPTURES = ["44621571bccc", "fb5f59006096", "723547b196b3"]
# Colonnes "documentées" (non meta) de nmf_event_light = toutes sauf meta
META_COLS = {
    "project_id","capture_id","seq","seq_last","event_code","system","second",
    "dimension","t_rel_s","decoder_version","schema_version","format_version",
    "decode_status","reasons","unknown","n_records","n_partial",
}

def main():
    db = SessionLocal()
    try:
        light_cols = [c for c in inspect(db.get_bind()).get_columns("nmf_event_light")
                      if c["name"] not in META_COLS]
        # NB clause pour test ≥1 doc field non-NULL
        nn_clause = " OR ".join([f'"{c["name"]}" IS NOT NULL' for c in light_cols])
        for cap in CAPTURES:
            print(f"\n=== G29 capture={cap} ===")
            pid = db.execute(text(
                "SELECT project_id FROM nmf_capture WHERE capture_id=:cap ORDER BY project_id LIMIT 1"
            ), {"cap": cap}).scalar()
            if not pid:
                print(f"NO_CAPTURE in nmf_capture")
                continue
            # Union all event codes across the 5 sources, GROUP BY event_code
            rows = db.execute(text(f"""
                WITH ev AS (
                  SELECT event_code, COUNT(*) AS n FROM stg_event_raw
                  WHERE project_id=:pid AND capture_id=:cap GROUP BY event_code
                ),
                se AS (
                  SELECT event_code, COUNT(*) AS n FROM stg_event
                  WHERE project_id=:pid AND capture_id=:cap GROUP BY event_code
                ),
                lsum AS (
                  SELECT event_code, SUM(n_records) AS n FROM nmf_event_light
                  WHERE project_id=:pid AND capture_id=:cap GROUP BY event_code
                ),
                lnn AS (
                  SELECT event_code, COUNT(*) AS n FROM nmf_event_light
                  WHERE project_id=:pid AND capture_id=:cap AND ({nn_clause})
                  GROUP BY event_code
                ),
                mp AS (
                  SELECT event_code, COUNT(*) AS n FROM measurement_points
                  WHERE project_id=:pid AND capture_id=:cap AND event_code IS NOT NULL
                  GROUP BY event_code
                )
                SELECT COALESCE(ev.event_code, se.event_code, lsum.event_code, lnn.event_code, mp.event_code) AS code,
                       COALESCE(ev.n,0) AS lignes_fichier, COALESCE(se.n,0) AS stg_event,
                       COALESCE(lsum.n,0) AS light_sum, COALESCE(lnn.n,0) AS light_doc_nn,
                       COALESCE(mp.n,0) AS mp
                FROM ev FULL OUTER JOIN se USING (event_code)
                        FULL OUTER JOIN lsum USING (event_code)
                        FULL OUTER JOIN lnn  USING (event_code)
                        FULL OUTER JOIN mp   USING (event_code)
                ORDER BY lignes_fichier DESC
            """), {"pid": pid, "cap": cap}).all()
            print(f"{'event_code':<16} {'file':>8} {'stg_e':>8} {'light_Σ':>10} {'ldocNN':>8} {'mp':>6}")
            for r in rows:
                print(f"{r[0]:<16} {int(r[1]):>8} {int(r[2]):>8} {int(r[3]):>10} {int(r[4]):>8} {int(r[5]):>6}")
            print(f"TOTAL rows={len(rows)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
