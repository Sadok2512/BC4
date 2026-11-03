"""Patch catalog 2.65.0 → 2.65.1 — LOT 1 FINAL (REPRISE 9).

Pas de modification du baked tree (les 5 319 leaves restent identiques).
Changement : les variantes NR dynamiques CQI_NR / DCI_NR / SCELLMOD sont
désormais émises par le pipeline runtime (décodeur 1.10.6+). Le bump
catalog_version → 2.65.1 trace cet enrichissement live.

Sortie : `app/kpi/catalog_release/catalog_2.65.1.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.65.0.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.65.1.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.65.1"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
leaves = sum(1 for n in cat["nodes"] if n.get("node_type") == "leaf")
print(f"wrote: {DST}")
print(f"total leaves (baked, unchanged): {leaves}")
print(f"sha256: {sha}")
