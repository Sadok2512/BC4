"""Patch catalog 2.63.2 → 2.64.0 — Lot 6 REPRISE 7.

Ajoute le champ `display_code` sur chaque leaf baked :
  - cell-type leaves (metric_id ex. `plaid_prbs@lte-type-0`) → display_code = metric_id
  - bare leaves (metric_id ex. `chi_rrc_state`) → display_code = metric_id

display_code = metric_id = unique par construction au niveau release (une
seule occurrence par triple (metric_id, cell_type, field_system) non
dupliquée). Garde : SELECT display_code, COUNT(*) GROUP BY display_code
HAVING COUNT(*) > 1 → 0 rows.

Sortie : `app/kpi/catalog_release/catalog_2.64.0.json` + sha256.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.63.2.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.64.0.json"

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]

enriched = 0
for n in nodes:
    if n.get("node_type") != "leaf":
        continue
    n["display_code"] = n.get("metric_id")
    enriched += 1

cat["catalog_version"] = "2.64.0"
cat["nodes"] = nodes

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"enriched leaves with display_code: {enriched}")
print(f"total leaves: {sum(1 for n in nodes if n.get('node_type') == 'leaf')}")
print(f"sha256: {sha}")

# Doublons display_code (après enrich) parmi leaves displayed
from collections import Counter
dc = Counter(n.get("display_code") for n in nodes if n.get("node_type") == "leaf" and n.get("displayed"))
dups = {k: v for k, v in dc.items() if v > 1}
print(f"display_code duplicates among displayed leaves: {len(dups)}")
for k, v in list(dups.items())[:10]:
    print(f"  {k}: {v}")
