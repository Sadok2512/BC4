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
  - **G25.2 (BC3 2026-10-26)** : feuille grise avec reason="Column not
    in decoder schema" alors qu'une colonne du même event/champ existe
    dans `nmf_event_light` ou `nmf_event_light_group` = FAIL (le mapping
    label-CSV → colonne-réelle doit venir du YAML du décodeur, pas d'une
    convention de nom).
"""
import json, sys
from collections import Counter
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

from app.nmf_decoder.schema import schemas, column as _col


def _available_columns(db):
    rows = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name IN ('nmf_event_light', 'nmf_event_light_group')"
    )).all()
    return {r[0] for r in rows}


def _event_fields_yaml():
    """event → set of (code, column_name) for header + group fields."""
    out = {}
    for ev, s in schemas().items():
        if not isinstance(s, dict): continue
        cols = set()
        def _walk(sch):
            for f in sch.get("header", []) or []:
                c = _col(f.get("code") or "")
                if c: cols.add(c)
            for g in sch.get("groups", []) or []:
                for f in g.get("fields", []) or []:
                    c = _col(f.get("code") or "")
                    if c: cols.add(c)
        _walk(s)
        for v in (s.get("_variants") or {}).values():
            _walk(v)
        out[ev] = cols
    return out


def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT project_id, payload FROM metrics_catalog_cache ORDER BY project_id"
        )).all()
        avail_cols = _available_columns(db)
        event_cols = _event_fields_yaml()
        total_orphans = 0
        total_dup_nodes = 0
        total_dup_metrics = 0
        total_false_grey = 0  # G25.2 — grey leaves qui ont une colonne existante
        print(f"{'project_id':<20} {'metrics':>8} {'leaves':>8} {'orphans':>8} "
              f"{'dup_node_ids':>13} {'dup_metric_codes':>17} {'false_grey':>11}")
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

            # 4) G25.2 — grey leaves avec `source_column` non vide (donc
            #    le YAML du décodeur a été consulté avec succès pour
            #    cette feuille) et pourtant marquées "Column not in
            #    decoder schema" dans le cache. Signature claire du bug
            #    mapping label-CSV → colonne-réelle.
            false_grey = []
            for n in nodes:
                if n.get("node_type") != "leaf": continue
                if n.get("reason") != "Column not in decoder schema": continue
                sc = n.get("source_column")
                if sc and sc in avail_cols:
                    false_grey.append((n.get("label") or n.get("metric_id"), sc))

            total_orphans += len(orphans)
            total_dup_nodes += len(dup_node_ids)
            total_dup_metrics += len(dup_codes)
            total_false_grey += len(false_grey)
            print(f"{pid:<20} {len(metrics):>8} {len(leaf_ids):>8} {len(orphans):>8} "
                  f"{len(dup_node_ids):>13} {len(dup_codes):>17} {len(false_grey):>11}")
            if dup_node_ids:
                print(f"  DUP_NODE_IDS[:3]={dup_node_ids[:3]}")
            if dup_codes:
                print(f"  DUP_METRIC_CODES[:3]={dup_codes[:3]}")
            if orphans:
                print(f"  ORPHANS[:3]={orphans[:3]}")
            if false_grey:
                print(f"  FALSE_GREY[:3]={false_grey[:3]}")

        verdict = ("PASS" if total_orphans == 0 and total_dup_nodes == 0
                   and total_dup_metrics == 0 and total_false_grey == 0 else "FAIL")
        print(f"G25_VERDICT {verdict} total_orphans={total_orphans} "
              f"total_dup_node_ids={total_dup_nodes} "
              f"total_dup_metric_codes={total_dup_metrics} "
              f"total_false_grey={total_false_grey}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
