"""Patch catalog 2.66.1 → 2.66.2 — REPRISE 13.

Changelog :
  - Décodeur 1.11.2 : chi_rrc_state agg='last' (était 'dominant' depuis
    REPRISE 8 P3). Tie-breaker min() du dominant conservé pour autres
    champs (`app/nmf_decoder/light.py:46`) — chi_rrc_state ne passe plus
    par cette logique.
  - Nouveau leaf synthétique `chi_rrc_state_timeline` injecté par
    `app/kpi/metrics_catalog_v4.py` à la fin de build_catalog_v4 : count
    brut sur `nmf_event_deep` sans bucketing light.
  - Settings > Catalogue KPI (SettingsLayout.tsx:12) masqué du menu.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.66.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.66.2.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.66.2"
cat["decoder_min_version"] = "1.11.2"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
leaves = sum(1 for n in cat["nodes"] if n.get("node_type") == "leaf")
print(f"wrote: {DST}")
print(f"total leaves (baked, unchanged): {leaves}")
print(f"decoder_min_version: {cat['decoder_min_version']}")
print(f"sha256: {sha}")
