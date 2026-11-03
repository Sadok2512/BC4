"""Patch catalog 2.66.2 → 2.67.0 — Chantier Mobilité étape 2.

Changements :
  1. Nouvelle catégorie `cat_LTE_mobility` sous tech_LTE.
  2. Events `ev_hos`, `ev_hof`, `ev_pbf` créés (étaient absents du baked).
  3. Reparent events `ev_hoa`, `ev_hoi`, `ev_rrre`, `ev_rrf`, `ev_crel` vers
     `cat_LTE_mobility`.
  4. Leaves HOS (hos_count), HOF (hof_reserved), PBF (pbf_esm_cause) exposés
     comme feuilles baked.

Note : les KPI dérivés agrégés (counts, ratios, duration AVG/P95/max) sont
injectés dynamiquement par `metrics_catalog_v4.py` au moment du build car
calculés sur `nmf_event_deep` scoped par capture — non statiques dans le
JSON release.

Sortie : `app/kpi/catalog_release/catalog_2.67.0.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.66.2.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.67.0.json"

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]
by_id = {n["node_id"]: n for n in nodes}

tech_lte = next((n for n in nodes if n.get("node_id") == "tech_LTE"), None)
assert tech_lte, "tech_LTE missing"

# 1) Catégorie LTE > Mobilité (si absente)
MOBILITY_CAT_ID = "cat_LTE_mobility"
if not any(n.get("node_id") == MOBILITY_CAT_ID for n in nodes):
    nodes.append({
        "node_id": MOBILITY_CAT_ID,
        "node_type": "category",
        "label": "Mobilité",
        "parent_id": "tech_LTE",
    })

# 2) Events HOA / HOS / HOF / HOI / RRRE / RRF / CREL / PBF → cat_LTE_mobility
#    Reparent si existe, créer sinon.
MOBILITY_EVENTS = [
    ("ev_hoa",  "HOA",  "Handover attempt (HOA)"),
    ("ev_hos",  "HOS",  "Handover success (HOS)"),
    ("ev_hof",  "HOF",  "Handover failure (HOF)"),
    ("ev_hoi",  "HOI",  "Handover info (HOI)"),
    ("ev_rrre", "RRRE", "RRC re-establishment (RRRE)"),
    ("ev_rrf",  "RRF",  "RRC failure (RRF)"),
    ("ev_crel", "CREL", "Cell reselection (CREL)"),
    ("ev_pbf",  "PBF",  "Packet bearer failure (PBF)"),
]
reparented = 0
created = 0
for ev_id, ev_code, ev_label in MOBILITY_EVENTS:
    existing = next((n for n in nodes if n.get("node_id") == ev_id), None)
    if existing:
        existing["parent_id"] = MOBILITY_CAT_ID
        reparented += 1
    else:
        nodes.append({
            "node_id": ev_id, "node_type": "event",
            "label": ev_label, "parent_id": MOBILITY_CAT_ID,
            "event": ev_code,
        })
        created += 1

# 3) Leaves pour HOS, HOF, PBF (absents du catalog)
# HOS n'a pas de champ métrique (juste context ID) → leaf count sythétique.
# HOF n'a que `hof_reserved` déjà dans event_light → leaf standard.
# PBF a `pbf_esm_cause` → leaf standard.
NEW_LEAVES = [
    ("lf_hos_count", "ev_hos", "HOS", "hos_count", "Handover success count",
     "KPI", "n", "nmf_event_light", None),
    ("lf_hof_reserved", "ev_hof", "HOF", "hof_reserved", "HOF reserved",
     "DIMENSION", "", "nmf_event_light", "hof_reserved"),
    ("lf_pbf_esm_cause", "ev_pbf", "PBF", "pbf_esm_cause", "PBF ESM cause",
     "KPI_CATEGORICAL", "enum", "nmf_event_light", "pbf_esm_cause"),
]
leaves_added = 0
for node_id, parent_id, event, metric_id, label, kind, unit, source_table, source_column in NEW_LEAVES:
    if any(n.get("node_id") == node_id for n in nodes):
        continue
    nodes.append({
        "node_id": node_id, "node_type": "leaf",
        "parent_id": parent_id, "label": label,
        "metric_id": metric_id, "display_code": metric_id,
        "event": event, "source_column": source_column,
        "type": "Integer", "unit": unit,
        "kind": kind, "displayed": True, "selectable": True,
        "proof": "NFF 2.50 / nmf_event_light observed",
    })
    leaves_added += 1

cat["nodes"] = nodes
cat["catalog_version"] = "2.67.0"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"events reparented: {reparented}, created: {created}")
print(f"leaves added: {leaves_added}")
print(f"sha256: {sha}")
