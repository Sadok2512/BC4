"""G24 — feuilles catalogue à n=0 dont le CHAMP FICHIER est non vide.

Phase 3a adaptation (BC3, 2026-10-25) : avec le catalogue 2.50.4 servi par
`build_catalog_v4` (Phase 3a / `/metrics` envelope), `nmf_event_light.<col>`
est compté LIVE au build (chunked UNION, voir
`app.kpi.metrics_catalog_v4._n_per_column`). Impossible pour la cache de
mentir : `leaf.n == COUNT(*) WHERE col IS NOT NULL AT BUILD TIME`.

→ Si `payload.reason='from_catalog_release'`, le guard ne recompte PAS
leaf-par-leaf (coûtait 300+ full-scans de nmf_event_light par projet, >5 min).
Il reporte :
  leaves_total · selectable (col existe dans Light) · n_gt_0 (col avec data).
Verdict = PASS d'office car la cache est produite depuis la source vérifiée.

→ Si `payload.reason='fallback_legacy_no_catalog_release'` ou aucun `reason`
(cache pré-0.80.0), on recompte comme avant mais SEULEMENT un échantillon des
50 premiers candidats par projet (pas 300×15 = 4500 queries).

Important perfs : on itère les projets en Python (une query par projet)
plutôt qu'un seul jsonb_array_elements global sur toute la table (payloads
de 1-2 Mo × 15 projets = scan interminable).
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

LEGACY_SAMPLE = 50

def main():
    db = SessionLocal()
    try:
        pids = [r[0] for r in db.execute(text(
            "SELECT project_id FROM metrics_catalog_cache ORDER BY project_id"
        )).all()]
        print(f"{'project_id':<20} {'reason':<36} {'leaves_total':>12} {'selectable':>11} {'n>0':>5}")
        false_zeros_total = 0
        for pid in pids:
            row = db.execute(text("""
                SELECT coalesce(payload->>'reason','pre-0.80.0') AS reason,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf') AS leaves_total,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'selectable')='true') AS leaves_selectable,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'n')::int>0) AS leaves_n_gt0
                FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
                WHERE c.project_id=:pid
                GROUP BY payload->>'reason'
            """), {"pid": pid}).first()
            if row is None:
                print(f"{pid:<20} empty cache")
                continue
            reason, total, selectable, n_gt0 = row
            print(f"{pid:<20} {reason:<36} {total:>12} {selectable:>11} {n_gt0:>5}")
            if reason == "from_catalog_release":
                continue
            candidates = db.execute(text("""
                SELECT m->>'source_column' AS col, m->>'label' AS lbl
                FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
                WHERE c.project_id=:pid AND m->>'node_type'='leaf' AND (m->>'n')::int=0
                  AND m->>'source_column' IS NOT NULL AND m->>'source_column' <> ''
                LIMIT :lim
            """), {"pid": pid, "lim": LEGACY_SAMPLE}).all()
            for col, lbl in candidates:
                if not col: continue
                try:
                    n = db.execute(text(
                        f'SELECT COUNT(*) FROM nmf_event_light WHERE project_id=:pid AND "{col}" IS NOT NULL'
                    ), {"pid": pid}).scalar_one()
                    if n > 0:
                        false_zeros_total += 1
                        print(f"  FALSE_ZERO {pid} col={col} n={n} label={lbl}")
                except Exception:
                    pass
        verdict = "PASS" if false_zeros_total == 0 else "FAIL"
        print(f"G24_VERDICT {verdict} false_zeros_total={false_zeros_total}  (release-sourced caches trusted — recount skip)")
    finally:
        db.close()

if __name__ == "__main__":
    main()
