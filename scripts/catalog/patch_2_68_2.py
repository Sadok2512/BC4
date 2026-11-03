"""Patch catalog 2.68.1 -> 2.68.2 — Mobilité 2d (patch).

Même baked JSON que 2.68.1. Bump pour invalider les caches via
cache_generation_stamp (nouveaux KPI SCG split + RRD NOT_AVAILABLE).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.68.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.68.2.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.68.2"
DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"sha256: {sha}")
