"""Patch catalog 2.65.1 → 2.65.2 — LOT 1 CLÔTURE Point 2 (SCELL NR).

Bump catalog_version pour tracer l'ajout du schéma SCELL_NR (décodeur 1.11.0,
moteur étendu avec `count_header_col` / `params_header_col` pour layout
header-interleaved). Les feuilles baked restent identiques (5 319) ; les
nouvelles colonnes scell_* / serving_cells group sont exposées par le
pipeline runtime via metrics_v3.definitions() + nmf_cell_second observations.

decoder_min_version bumpé à 1.11.0 (contrat : schéma SCELL_NR nécessite le
moteur étendu).

Sortie : `app/kpi/catalog_release/catalog_2.65.2.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.65.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.65.2.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.65.2"
cat["decoder_min_version"] = "1.11.0"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
leaves = sum(1 for n in cat["nodes"] if n.get("node_type") == "leaf")
print(f"wrote: {DST}")
print(f"total leaves (baked, unchanged): {leaves}")
print(f"decoder_min_version: {cat['decoder_min_version']}")
print(f"sha256: {sha}")
