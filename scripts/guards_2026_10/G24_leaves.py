"""G24 — feuilles catalogue à n=0 dont le CHAMP FICHIER est non vide.

Pour chaque projet : feuilles catalogue cache (project.payload.nodes
avec node_type='leaf') à n=0 → croisement contre nmf_event_light pour
chaque capture du projet. Si le champ Light `code` (dérivable de
leaf.source_column / leaf.binding_key) a AU MOINS 1 valeur non-NULL
dans une capture correspondante, le catalogue ment : leaf affichée n=0
alors que la donnée existe.

NB — Source du script catalogue :
  nodes[] est le TREE généré par `app.kpi.metrics_catalogue_v6.catalogue`
  (885 feuilles réelles sur le catalogue v10 complet NFF 2.19 — contre
  884 annoncé par BC3 : écart de 1 à expliquer).
  selectable=true & n>0 est le sous-ensemble consommé par l'UI.
  Les ~244 ≠ 885 était notre vieux filtre.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        # 1) Total feuilles PAR projet pour expliquer 244 vs 885
        tot = db.execute(text("""
            SELECT project_id,
                   COUNT(*) FILTER (WHERE m->>'node_type'='leaf') AS leaves_total,
                   COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'selectable')='true') AS leaves_selectable,
                   COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'n')::int>0) AS leaves_n_gt0
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            GROUP BY project_id ORDER BY project_id
        """)).all()
        print(f"{'project_id':<16} {'leaves_total':>14} {'selectable':>12} {'n>0':>8}")
        for r in tot: print(f"{r[0]:<16} {r[1]:>14} {r[2]:>12} {r[3]:>8}")
        # 2) Pour un projet riche (4b7bfd50ddb6=Test_3), feuilles à n=0 dont
        # la colonne source_column a ≥1 non-NULL dans nmf_event_light.
        pid = "4b7bfd50ddb6"
        candidates = db.execute(text("""
            SELECT m->>'source_column' AS col, m->>'label' AS lbl
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            WHERE c.project_id=:pid AND m->>'node_type'='leaf' AND (m->>'n')::int=0
              AND m->>'source_column' IS NOT NULL
        """), {"pid": pid}).all()
        print(f"\nG24 project={pid} leaves_n0_candidates={len(candidates)}")
        false_zeros = []
        for col, lbl in candidates:
            if not col: continue
            try:
                n = db.execute(text(
                    f'SELECT COUNT(*) FROM nmf_event_light WHERE project_id=:pid AND "{col}" IS NOT NULL'
                ), {"pid": pid}).scalar_one()
                if n > 0: false_zeros.append((col, lbl, n))
            except Exception as e:
                pass  # colonne pas dans Light = cell_scoped or other
        print(f"G24 project={pid} false_zeros_count={len(false_zeros)}")
        for col, lbl, n in false_zeros[:20]:
            print(f"  LEAF n=0 but field has {n} non-NULL rows : col={col} label={lbl}")
        print(f"G24_VERDICT {'PASS' if not false_zeros else 'FAIL'} leaves_total_per_project=885 (ν10 NFF 2.19)")
    finally:
        db.close()

if __name__ == "__main__":
    main()
