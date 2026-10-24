"""G18b — parité feuilles /metrics API vs catalogue régénéré en direct.

- Côté A : feuilles exposées par `GET /projects/{pid}/metrics` = lecture du
  cache metrics_catalog_cache.payload.nodes (filtré leaf).
- Côté B : feuilles produites par `catalogue_v6(db, pid, metric_rows)` RE-
  généré en direct depuis les sources (nmf_event_light + schémas YAML).

Toute divergence (feuilles côté A manquantes côté B ou l'inverse) =
dérive de cache / catalogue partiellement périmé.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal
from app.kpi.metrics_v3 import catalog as catalog_v3
from app.kpi.metrics_catalogue_v6 import catalogue as catalogue_v6

def main():
    db = SessionLocal()
    try:
        pids = [r[0] for r in db.execute(text(
            "SELECT project_id FROM metrics_catalog_cache ORDER BY project_id"
        )).all()]
        divergent = 0
        for pid in pids:
            # A — cache UI
            cached_nodes = db.execute(text(
                "SELECT payload->'nodes' FROM metrics_catalog_cache WHERE project_id=:pid"
            ), {"pid": pid}).scalar_one()
            cached_leaves = {n.get("node_id") for n in cached_nodes if n.get("node_type") == "leaf"}
            # B — regénéré direct
            metric_rows = catalog_v3(db, pid)
            fresh = catalogue_v6(db, pid, metric_rows)
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
        print(f"G18b_VERDICT {verdict} projects={len(pids)} divergent={divergent}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
