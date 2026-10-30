"""G18b — parité `/metrics` cache vs catalogue régénéré en direct (sans set()).

Phase 3b préalable (BC3, 2026-10-25) — on compare les LISTES (pas des
`set()`) de `node_id` leaf : un doublon dans l'une des deux listes =
FAIL, car le contrat 2.50.5 impose 5115 ids uniques pour 5115 feuilles.

- Côté A : feuilles dans metrics_catalog_cache.payload.nodes (filtré leaf),
  ORDRE préservé.
- Côté B : feuilles produites par `build_catalog_v4(db, pid, current)`,
  ORDRE préservé.

Divergences détectées :
  - longueur(A) ≠ longueur(B)                     → divergent
  - doublon dans A ou B                           → divergent
  - éléments présents dans A pas dans B           → divergent (only_cache)
  - éléments présents dans B pas dans A           → divergent (only_fresh)
"""
import argparse, sys
from collections import Counter
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.kpi.catalog_release.registry import current_catalog
from guard_runtime import session_local_or_fail
from scope_args import add_scope_args, resolve_scope

SessionLocal = session_local_or_fail("G18b")


def _leaves_list(nodes):
    """Return list (ordre préservé) de node_id pour chaque leaf."""
    return [n.get("node_id") for n in nodes if n.get("node_type") == "leaf"]


def main():
    ap = argparse.ArgumentParser()
    add_scope_args(ap)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        try:
            project_id, capture_ids = resolve_scope(db, args)
        except ValueError as exc:
            print(f"G18b VERDICT=FAIL reason=scope_error detail={exc}")
            sys.exit(1)
        print(f"G18b scope: project_id={project_id} captures={capture_ids}")
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
                return {"nodes": catalogue_v6(db, pid, metric_rows).get("nodes", [])}
            mode = "legacy (no catalog_release)"
        print(f"G18b mode: {mode}")

        pids = [r[0] for r in db.execute(text(
            "SELECT project_id FROM metrics_catalog_cache "
            "WHERE project_id=:pid ORDER BY project_id"
        ), {"pid": project_id}).all()]
        divergent = 0
        print(f"{'project_id':<20} {'cached':>7} {'fresh':>7} {'dup_cache':>10} "
              f"{'dup_fresh':>10} {'only_cache':>11} {'only_fresh':>11}")
        for pid in pids:
            cached_nodes = db.execute(text(
                "SELECT payload->'nodes' FROM metrics_catalog_cache WHERE project_id=:pid"
            ), {"pid": pid}).scalar_one() or []
            cached_list = _leaves_list(cached_nodes)
            fresh_list = _leaves_list(fresh_fn(pid).get("nodes", []))

            cached_counts = Counter(cached_list)
            fresh_counts = Counter(fresh_list)
            dup_cache = sum(v - 1 for v in cached_counts.values() if v > 1)
            dup_fresh = sum(v - 1 for v in fresh_counts.values() if v > 1)

            # Multiset difference : combien dans A manquent dans B et vice-versa
            only_cache = (cached_counts - fresh_counts)
            only_fresh = (fresh_counts - cached_counts)

            print(f"{pid:<20} {len(cached_list):>7} {len(fresh_list):>7} "
                  f"{dup_cache:>10} {dup_fresh:>10} "
                  f"{sum(only_cache.values()):>11} {sum(only_fresh.values()):>11}")

            is_div = (
                len(cached_list) != len(fresh_list)
                or dup_cache > 0 or dup_fresh > 0
                or len(only_cache) > 0 or len(only_fresh) > 0
            )
            if is_div:
                divergent += 1
                if only_cache:
                    print(f"    only_cache[:3]={list(only_cache.keys())[:3]}")
                if only_fresh:
                    print(f"    only_fresh[:3]={list(only_fresh.keys())[:3]}")

        # 0.89.5 — garde sans témoin = FAIL. Un garde qui n'a examiné aucun
        # projet (cache vide) ne prouve rien ; il doit lever, pas renvoyer PASS.
        if len(pids) == 0:
            print(f"G18b VERDICT=FAIL reason=no_witness examined=0 "
                  f"(metrics_catalog_cache vide — upload un projet d'abord)")
            sys.exit(1)
        verdict = "PASS" if divergent == 0 else "FAIL"
        print(f"G18b VERDICT={verdict} projects={len(pids)} divergent={divergent}  "
              f"mode={mode}")
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
