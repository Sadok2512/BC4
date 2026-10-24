"""G24 — feuilles catalogue : chaque leaf avec n>0 doit avoir une sélection
non vide (selection != NULL ET selectable=true), sinon elle est invisible/
inutilisable côté UI.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT project_id, m->>'label' AS label, m->>'n' AS n,
                   m->>'selectable' AS sel, m->>'selection' AS code
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            WHERE (m->>'node_type')='leaf' AND (m->>'n')::int > 0
        """)).all()
        total = len(rows)
        bad = [r for r in rows if r[3] != "true" or not r[4]]
        for r in bad[:10]:
            print(f"G24 BAD pid={r[0]} label={r[1]} n={r[2]} sel={r[3]} code={r[4]}")
        verdict = "PASS" if not bad else "FAIL"
        print(f"G24_VERDICT {verdict} total_leaves={total} unusable={len(bad)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
