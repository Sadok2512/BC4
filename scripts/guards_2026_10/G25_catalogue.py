"""G25 — chaque `metrics[].code` doit être consommable par ≥ 1 `leaf.selection`,
ET aucun duplicat dans metrics[].code ni dans nodes[].node_id.

Phase 3b préalable (BC3, 2026-10-25) — réécrit SANS `set()` : un seul
doublon de `node_id` ou de `metrics[].code` dans la cache = FAIL. Le but
n'est plus seulement de détecter des orphelins mais aussi de vérifier
l'unicité d'identité des positions (contrat 2.50.5 : 5115 ids pour 5115
feuilles).

Verdict :
  - orphans > 0        → FAIL
  - dup node_ids > 0   → FAIL (chaque position doit être unique)
  - dup metric codes > 0 → FAIL (metrics[] est une table, pas un multiset)
"""
import json, sys
from collections import Counter
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal


def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT project_id, payload FROM metrics_catalog_cache ORDER BY project_id"
        )).all()
        total_orphans = 0
        total_dup_nodes = 0
        total_dup_metrics = 0
        print(f"{'project_id':<20} {'metrics':>8} {'leaves':>8} {'orphans':>8} "
              f"{'dup_node_ids':>13} {'dup_metric_codes':>17}")
        for pid, payload in rows:
            if isinstance(payload, str): payload = json.loads(payload)
            metrics = payload.get("metrics", [])
            nodes = payload.get("nodes", [])

            # 1) duplicat check — leaves node_ids
            leaf_ids = [n["node_id"] for n in nodes if n.get("node_type") == "leaf"]
            node_id_counts = Counter(leaf_ids)
            dup_node_ids = [k for k, v in node_id_counts.items() if v > 1]

            # 2) duplicat check — metrics codes
            codes = [m.get("code") for m in metrics if m.get("code")]
            code_counts = Counter(codes)
            dup_codes = [k for k, v in code_counts.items() if v > 1]

            # 3) orphans — chaque code doit matcher ≥ 1 selection (liste, pas set)
            selections = [n.get("selection") for n in nodes
                          if n.get("node_type") == "leaf" and n.get("selection")]
            orphans = []
            for code in codes:
                matched = False
                for sel in selections:
                    if sel == code or sel.startswith(code + "@"):
                        matched = True
                        break
                if not matched:
                    orphans.append(code)

            total_orphans += len(orphans)
            total_dup_nodes += len(dup_node_ids)
            total_dup_metrics += len(dup_codes)
            print(f"{pid:<20} {len(metrics):>8} {len(leaf_ids):>8} {len(orphans):>8} "
                  f"{len(dup_node_ids):>13} {len(dup_codes):>17}")
            if dup_node_ids:
                print(f"  DUP_NODE_IDS[:3]={dup_node_ids[:3]}")
            if dup_codes:
                print(f"  DUP_METRIC_CODES[:3]={dup_codes[:3]}")
            if orphans:
                print(f"  ORPHANS[:3]={orphans[:3]}")

        verdict = ("PASS" if total_orphans == 0 and total_dup_nodes == 0
                   and total_dup_metrics == 0 else "FAIL")
        print(f"G25_VERDICT {verdict} total_orphans={total_orphans} "
              f"total_dup_node_ids={total_dup_nodes} "
              f"total_dup_metric_codes={total_dup_metrics}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
