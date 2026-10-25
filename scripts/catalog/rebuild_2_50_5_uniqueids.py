"""Catalog 2.50.5 — assigne un `node_id` unique par position aux feuilles.

Phase 3b préalable (BC3, 2026-10-25) — le 2.50.4 avait 5115 feuilles
`displayed=true` mais seulement 3625 `node_id` uniques (699 node_ids
dupliqués, le pire étant `lf_dreq_timeout` x28). Cause : le builder
`scripts/catalog/build_catalog.py` dérive `node_id` de
`(event_slug, field_slug[, cell_type])` ; quand la CSV NFF 2.50 contient
plusieurs rangs avec le même `(event, name)` (sections "Parameters",
"Parameters for LTE", "Parameters for NR", ou champs documentés plusieurs
fois avec field_no différents), les feuilles collisionnent.

Ce script est un POST-PROCESSEUR du JSON 2.50.4 :
  - préserve 100% du contenu, y compris `generated_at` (traçabilité)
  - ne touche QUE les `node_id` des feuilles dupliquées
  - suffixe par `_r<ordinal>` où <ordinal> est l'index zero-based de
    l'occurrence dans l'ordre d'apparition. Première occurrence = `_r0`
    (préserve `lf_dreq_timeout` → `lf_dreq_timeout_r0` pour chaque dup)
  - garantit : `len({n.node_id for n in nodes}) == len(nodes)` sur TOUT
    le tree (pas juste leaves — on vérifie aussi les non-leaves pour
    détecter d'autres collisions).

Usage (depuis bc4-back/) :
  python scripts/catalog/rebuild_2_50_5_uniqueids.py \
    --in app/kpi/catalog_release/catalog_2.50.4.json \
    --out app/kpi/catalog_release/catalog_2.50.5.json \
    --version 2.50.5 \
    --commit
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sqlalchemy import text  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    src = json.loads(Path(args.src).read_text())
    nodes_in = src["nodes"]

    # 1) Count occurrences by current node_id (for stats)
    occ = defaultdict(int)
    for n in nodes_in:
        occ[n["node_id"]] += 1
    dup_ids = [k for k, v in occ.items() if v > 1]
    dup_positions = sum(v - 1 for v in occ.values() if v > 1)
    print(f"[rebuild] input leaves+nodes={len(nodes_in)} unique_node_ids={len(occ)} "
          f"dup_node_ids={len(dup_ids)} dup_positions={dup_positions}")

    # 2) Rewrite node_ids : pour chaque collision, suffixer _r<i> au cas où
    #    un node_id apparaît >=1 fois, pour PRÉSERVER la stabilité des IDs
    #    non-dupliqués, on ne touche que ceux qui collisionnent. Mais pour
    #    la lisibilité et éviter un "lf_x" + "lf_x_r1" (base + suffixé),
    #    on applique _r0 au PREMIER aussi quand il y a au moins une dup.
    counter: dict[str, int] = defaultdict(int)
    nodes_out = []
    for n in nodes_in:
        n2 = dict(n)
        old_id = n2["node_id"]
        if occ[old_id] > 1:
            idx = counter[old_id]
            counter[old_id] += 1
            n2["node_id"] = f"{old_id}_r{idx}"
        nodes_out.append(n2)

    # 3) Vérifier unicité
    final_ids = [n["node_id"] for n in nodes_out]
    final_set = set(final_ids)
    if len(final_ids) != len(final_set):
        from collections import Counter
        remaining = [k for k, v in Counter(final_ids).items() if v > 1]
        raise SystemExit(f"[rebuild] FATAL still-duplicate node_ids after rewrite: "
                         f"{len(remaining)} ids — {remaining[:5]}")
    print(f"[rebuild] output unique_node_ids={len(final_set)}  n_nodes={len(nodes_out)}  "
          f"invariant: unique_ids == n_nodes ✓")

    displayed_leaves = [n for n in nodes_out if n.get("node_type") == "leaf" and n.get("displayed")]
    print(f"[rebuild] displayed_leaves={len(displayed_leaves)}  "
          f"unique_displayed_leaf_ids={len({n['node_id'] for n in displayed_leaves})}")

    # 4) Build payload avec métadonnées
    payload = dict(src)
    payload["catalog_version"] = args.version
    payload["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload["nodes"] = nodes_out
    # Note : n_leaves, n_leaves_displayed, n_metrics restent identiques
    # (on n'a pas changé le nombre de feuilles, juste leurs ids).

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"[rebuild] out={out_path} sha256={sha}")

    if args.commit:
        db = SessionLocal()
        try:
            db.execute(text("UPDATE catalog_release SET is_current=FALSE WHERE is_current=TRUE"))
            db.execute(text(
                "INSERT INTO catalog_release(version, spec_version, decoder_min_version, "
                "sha256, n_categories, n_metrics, n_leaves, changelog, is_current) "
                "VALUES(:v,:s,:d,:sha,:nc,:nm,:nl,:cl,TRUE) "
                "ON CONFLICT(version) DO UPDATE SET sha256=excluded.sha256, "
                "n_categories=excluded.n_categories, n_metrics=excluded.n_metrics, "
                "n_leaves=excluded.n_leaves, is_current=TRUE"
            ), {
                "v": args.version,
                "s": payload["spec_version"],
                "d": payload["decoder_min_version"],
                "sha": sha,
                "nc": payload["n_categories"],
                "nm": payload["n_metrics"],
                "nl": payload["n_leaves"],
                "cl": f"post-process 2.50.4 → unique node_ids ({dup_positions} dup positions suffixed _r<i>)"
            })
            db.commit()
            print(f"[rebuild] catalog_release row v={args.version} is_current=TRUE")
        finally:
            db.close()


if __name__ == "__main__":
    main()
