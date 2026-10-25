"""G18b — parité feuilles /metrics API vs catalogue régénéré en direct.

Phase 3a adaptation (BC3, 2026-10-25) : avec `catalog_release.is_current`
posé, le `/metrics` endpoint prend le chemin `build_catalog_v4` (Phase 3a) ;
on compare donc le cache contre un rebuild v4 fraîchement généré.

- Côté A : feuilles dans metrics_catalog_cache.payload.nodes (filtré leaf).
- Côté B : feuilles produites par `build_catalog_v4(db, pid, current)` ré-généré.

Toute divergence (feuilles côté A manquantes côté B ou l'inverse) = dérive
de cache / catalogue partiellement périmé.

Si `catalog_release` est vide (bootstrap frais), on retombe sur le chemin
legacy catalogue_v6 (identique à l'ancien G18b < 0.80.0).
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal
from app.kpi.catalog_release.registry import current_catalog


def main():
    db = SessionLocal()
    try:
        cur = current_catalog(db)
        if cur:
            from app.kpi.metrics_catalog_v4 import build_catalog_v4
            fresh_fn = lambda pid: build_catalog_v4(db, pid, cur)
            mode = f"v4 (catalog_release={cur.version})"
        else:
            from app.kpi.metrics_v3 import catalog as catalog_v3
            from app.kpi.metrics_catalogue_v6 import catalogue as catalogue_v6
            def fresh_fn(pid):
                metric_rows = catalog_v3(db, pid)
                p = catalogue_v6(db, pid, metric_rows)
                return {"nodes": p.get("nodes", [])}
            mode = "legacy (no catalog_release)"
        print(f"G18b mode: {mode}")

        pids = [r[0] for r in db.execute(text(
            "SELECT project_id FROM metrics_catalog_cache ORDER BY project_id"
        )).all()]
        divergent = 0
        for pid in pids:
            cached_nodes = db.execute(text(
                "SELECT payload->'nodes' FROM metrics_catalog_cache WHERE project_id=:pid"
            ), {"pid": pid}).scalar_one() or []
            cached_leaves = {n.get("node_id") for n in cached_nodes if n.get("node_type") == "leaf"}
            fresh = fresh_fn(pid)
            fresh_leaves = {n.get("node_id") for n in fresh.get("nodes", []) if n.get("node_type") == "leaf"}
            only_cache = cached_leaves - fresh_leaves
            only_fresh = fresh_leaves - cached_leaves
            print(f"G18b {pid}: cached={len(cached_leaves)} fresh={len(fresh_leaves)} "
                  f"only_cache={len(only_cache)} only_fresh={len(only_fresh)}")
            if only_cache or only_fresh:
                divergent += 1
                for n in list(only_cache)[:3]: print(f"    only_cache {n}")
                for n in list(only_fresh)[:3]: print(f"    only_fresh {n}")
        verdict = "PASS" if divergent == 0 else "FAIL"
        print(f"G18b_VERDICT {verdict} projects={len(pids)} divergent={divergent}  mode={mode}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
