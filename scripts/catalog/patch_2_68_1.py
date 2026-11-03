"""Patch catalog 2.68.0 -> 2.68.1 — Mobilité 2c (patch : corrections).

Changements :
  Même baked JSON que 2.68.0 (0 node ajouté). Bump de version pour
  invalider les caches via cache_generation_stamp afin que les KPI
  dérivés tombent sous le nouveau code (lte_ho_duration_* =
  NOT_AVAILABLE, abnormal release par cause connue uniquement,
  CAUSE_UNKNOWN séparé, retries RRRE status filtrés, SCG add/release
  via nmf_event_group).

Sortie : `app/kpi/catalog_release/catalog_2.68.1.json` + sha256.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.68.0.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.68.1.json"

cat = json.loads(SRC.read_text())
cat["catalog_version"] = "2.68.1"
DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"sha256: {sha}")
