"""Patch catalog 2.67.1 -> 2.68.0 — Mobilité 2b (minor : nouveaux KPI).

Changements :
  1. Nouvelles catégories sous tech_LTE :
     - cat_LTE_scg (ENDC SCG modifications / failures)
     - cat_LTE_access (RRC setup, RRC abnormal release, NAS TAU/LAU)
  2. Events ajoutés baked (jamais présents dans le release) :
     - ev_rrf (RRC setup failure, NFF 2.50 p.418)
     - ev_tuf (TAU failure)
     - ev_luf (LAU failure)
  3. Les compteurs d'events (RRF, TUF, LUF) et tous les KPI dérivés
     (RLF detail, SCG failure rate, success rates, retries, HO duration
     sans filtre, aberrant count) sont injectés dynamiquement par
     `metrics_catalog_v4.py` — non statiques.

Sortie : `app/kpi/catalog_release/catalog_2.68.0.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.67.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.68.0.json"

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]

by_id = {n.get("node_id"): n for n in nodes}
tech_lte = next((n for n in nodes if n.get("node_id") == "tech_LTE"), None)
assert tech_lte, "tech_LTE missing"

# 1) Nouvelles catégories sous tech_LTE
NEW_CATS = [
    ("cat_LTE_scg",    "ENDC SCG",          "tech_LTE"),
    ("cat_LTE_access", "Accessibilité et NAS", "tech_LTE"),
]
cats_added = 0
for cat_id, label, parent_id in NEW_CATS:
    if any(n.get("node_id") == cat_id for n in nodes):
        continue
    nodes.append({
        "node_id": cat_id, "node_type": "category",
        "parent_id": parent_id, "label": label, "displayed": True,
    })
    cats_added += 1

# 2) Events baked absents : RRF, TUF, LUF
NEW_EVENTS = [
    ("ev_rrf", "cat_LTE_access", "RRF", "RRC setup failure"),
    ("ev_tuf", "cat_LTE_access", "TUF", "TAU failure"),
    ("ev_luf", "cat_LTE_access", "LUF", "LAU failure"),
]
events_added = 0
for node_id, parent_id, ev_code, label in NEW_EVENTS:
    if any(n.get("node_id") == node_id for n in nodes):
        continue
    nodes.append({
        "node_id": node_id, "node_type": "event",
        "parent_id": parent_id, "label": label, "displayed": True,
        "event": ev_code,
    })
    events_added += 1

cat["nodes"] = nodes
cat["catalog_version"] = "2.68.0"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"categories added: {cats_added}")
print(f"events added: {events_added}")
print(f"sha256: {sha}")
