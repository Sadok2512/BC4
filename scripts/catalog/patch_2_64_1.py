"""Patch catalog 2.64.0 → 2.64.1 — REPRISE 8 Points 1 à 3.

Ajouts baked JSON :
  - `enums.rrc_state = [{value:1, label:"Idle"}, {value:2, label:"Connected"}]`
    (NFF 2.50 CHI Parameters for LTE #2, p.326).
  - Pour chi_rrc_state leaf : `enum_ref: "rrc_state"` + `kind: "KPI_CATEGORICAL"`
    (aligne baked avec runtime).

Points 1 (unités) et 2 (align metrics[] with tree) sont purement code (voir
metrics_catalog_v4.py:1261 et :1308). Pas de modif baked JSON requise, mais
bump catalog version pour tracer la cohérence.

Sortie : `app/kpi/catalog_release/catalog_2.64.1.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.64.0.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.64.1.json"

cat = json.loads(SRC.read_text())

# Ajouter l'enum rrc_state au dict top-level `enums`
enums = cat.setdefault("enums", {})
enums["rrc_state"] = [
    {"value": 1, "label": "Idle"},
    {"value": 2, "label": "Connected"},
]

# Mettre à jour chi_rrc_state leaf : enum_ref + kind=KPI_CATEGORICAL baked
updated = 0
for n in cat["nodes"]:
    if n.get("metric_id") == "chi_rrc_state" and n.get("node_type") == "leaf":
        n["enum_ref"] = "rrc_state"
        n["enum_values"] = {"1": "Idle", "2": "Connected"}
        n["kind"] = "KPI_CATEGORICAL"
        n["label"] = "LTE RRC state"
        updated += 1

if updated != 1:
    print(f"ERROR: expected 1 chi_rrc_state leaf, got {updated}", file=sys.stderr)
    sys.exit(1)

cat["catalog_version"] = "2.64.1"
DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"enums.rrc_state added, chi_rrc_state leaf updated: {updated}")
print(f"sha256: {sha}")
