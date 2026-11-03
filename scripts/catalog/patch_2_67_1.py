"""Patch catalog 2.67.0 -> 2.67.1 — Étape 3c.

Changement : version bump uniquement (same baked content). Nécessaire pour
invalider les caches `metrics_catalog_cache` via `cache_generation_stamp`
après le fix de `metrics_catalog_v4.py:1133` (préservation de l'identité
baked pour les leaves spécialisées type `dci_dci_format_f10@6`).

Sortie : `app/kpi/catalog_release/catalog_2.67.1.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.67.0.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.67.1.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.67.1"
DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"sha256: {sha}")
