"""Patch catalog 2.63.1 → 2.63.2 — Point 2 REPRISE 7.

Changements minimaux et vérifiables :
  (1) Supprime 5 doublons CHI "(bloc LTE #NN)" dont la `source_column` est
      identique au leaf primaire :
          chi_pci_f21        → doublon de chi_pci
          chi_tm_f22         → doublon de chi_tm
          chi_ul_dl_config_f24 → doublon de chi_ul_dl_config
          chi_cp_f25         → doublon de chi_cp
          chi_special_subframe_f32 → doublon de chi_special_subframe
  (2) Renomme le label de `chi_rrc_state` : « RRC state (bloc UMTS FDD) »
      → « LTE RRC state ».

PAS re-parenté : la restructure complète (CHI sous LTE/NR au lieu de
Shared) + fusion des 32 autres "(bloc X)" + enum Idle/Connected sont
reportés à un lot ultérieur (changement plus large).

Sortie : `app/kpi/catalog_release/catalog_2.63.2.json` + sha256.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.63.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.63.2.json"

LTE_DUP_IDS = {
    "chi_pci_f21",
    "chi_tm_f22",
    "chi_ul_dl_config_f24",
    "chi_cp_f25",
    "chi_special_subframe_f32",
}

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]

dropped = 0
relabel = 0
out = []
for n in nodes:
    if n.get("node_type") == "leaf" and n.get("metric_id") in LTE_DUP_IDS:
        dropped += 1
        continue
    if n.get("metric_id") == "chi_rrc_state" and n.get("node_type") == "leaf":
        n = dict(n)
        n["label"] = "LTE RRC state"
        relabel += 1
    out.append(n)

if dropped != 5 or relabel != 1:
    print(f"ERROR: expected drop=5 relabel=1, got drop={dropped} relabel={relabel}", file=sys.stderr)
    sys.exit(1)

cat["nodes"] = out
cat["catalog_version"] = "2.63.2"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
leaves = sum(1 for n in out if n.get("node_type") == "leaf")
print(f"wrote: {DST}")
print(f"dropped LTE #NN duplicate leaves: {dropped}")
print(f"relabeled chi_rrc_state leaves: {relabel}")
print(f"total leaves in nodes[]: {leaves}")
print(f"sha256: {sha}")
