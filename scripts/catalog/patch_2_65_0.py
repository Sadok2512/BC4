"""Patch catalog 2.64.1 → 2.65.0 — REPRISE 8 Point 4.

Reparentage des 116 feuilles CHI hors de `cat_Shared_services_tasks` :
  - leaves (bloc LTE) ou sans marqueur    → `cat_LTE_signalling` (tech_LTE)
  - leaves (bloc NR)                       → nouvelle `cat_NR_signalling` (tech_NR)
  - leaves (bloc GSM/TETRA/UMTS FDD/UMTS TD-SCDMA/EVDO/iDEN/WiMAX/GAN WLAN/
    cdmaOne and CDMA 1x) → `cat_Other_legacy_umts_cdma_dvb` (tech_Other)

L'event `ev_chi` est dupliqué en `ev_chi_lte` / `ev_chi_nr` / `ev_chi_other`
sous leur catégorie respective. L'ancien `ev_chi` est retiré.

Labels nettoyés : strip du marqueur "(bloc X)" (ne reste que le nom nu).
Doublons `source_column` au sein de la même tech → garder la première occurrence.

Sortie : `app/kpi/catalog_release/catalog_2.65.0.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.64.1.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.65.0.json"

BLOC_RE = re.compile(r"\s*\(bloc [^)]+\)\s*")
BLOC_MATCH_RE = re.compile(r"\(bloc ([^)]+)\)")

TECH_FROM_BLOC = {
    "LTE": "lte",
    "NR": "nr",
    # Toutes les autres techs → "other"
}

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]
by_id = {n["node_id"]: n for n in nodes}

# Trouver les catégories cibles
cat_lte_sig = next((n for n in nodes if n.get("node_type")=="category" and n["label"]=="Signalling" and n.get("parent_id")=="tech_LTE"), None)
cat_other = next((n for n in nodes if n.get("node_type")=="category" and n.get("node_id")=="cat_Other_legacy_umts_cdma_dvb"), None)
assert cat_lte_sig and cat_other, "cat_LTE_signalling or cat_Other_legacy_umts_cdma_dvb missing"

# Créer cat_NR_signalling s'il manque
cat_nr_sig = next((n for n in nodes if n.get("node_type")=="category" and n["label"]=="Signalling" and n.get("parent_id")=="tech_NR"), None)
if cat_nr_sig is None:
    cat_nr_sig = {
        "node_id": "cat_NR_signalling",
        "node_type": "category",
        "label": "Signalling",
        "parent_id": "tech_NR",
    }
    nodes.append(cat_nr_sig)

# Créer les 3 events CHI
ev_chi_lte = {
    "node_id": "ev_chi_lte",
    "node_type": "event",
    "label": "CHI",
    "parent_id": cat_lte_sig["node_id"],
    "event": "CHI",
}
ev_chi_nr = {
    "node_id": "ev_chi_nr",
    "node_type": "event",
    "label": "CHI",
    "parent_id": cat_nr_sig["node_id"],
    "event": "CHI",
}
ev_chi_other = {
    "node_id": "ev_chi_other",
    "node_type": "event",
    "label": "CHI (legacy)",
    "parent_id": cat_other["node_id"],
    "event": "CHI",
}
nodes.extend([ev_chi_lte, ev_chi_nr, ev_chi_other])

# Reparent CHI leaves
def tech_for_leaf(n):
    label = n.get("label") or ""
    m = BLOC_MATCH_RE.search(label)
    bloc = m.group(1) if m else None
    if bloc == "NR":
        return "nr"
    if bloc == "LTE" or bloc is None:
        return "lte"
    return "other"

chi_leaves = [n for n in nodes if n.get("event") == "CHI" and n.get("node_type") == "leaf"]
counts_before = len(chi_leaves)

# Dedup per (tech, source_column) : keep first occurrence
seen = set()
chi_leaves_sorted = sorted(chi_leaves, key=lambda n: (n.get("source_column") or "", n.get("metric_id") or ""))
new_parents = {"lte": ev_chi_lte["node_id"], "nr": ev_chi_nr["node_id"], "other": ev_chi_other["node_id"]}

kept = 0
removed_dup = 0
reparented = 0
to_remove = set()
for n in chi_leaves_sorted:
    tech = tech_for_leaf(n)
    sc = n.get("source_column")
    if sc:
        key = (tech, sc)
        if key in seen:
            to_remove.add(n["node_id"])
            removed_dup += 1
            continue
        seen.add(key)
    # Reparent
    old_parent = n.get("parent_id")
    n["parent_id"] = new_parents[tech]
    # Clean label from "(bloc X)" marker
    old_label = n.get("label") or ""
    new_label = BLOC_RE.sub("", old_label).strip()
    if new_label != old_label:
        n["label"] = new_label
    reparented += 1
    kept += 1

# Remove duplicates
nodes[:] = [n for n in nodes if n["node_id"] not in to_remove]

# Remove old ev_chi (replaced by 3 variants). Reparent any OTHER leaf that pointed to ev_chi (none).
old_ev_chi = next((n for n in nodes if n.get("node_id") == "ev_chi"), None)
leaves_still_on_ev_chi = [n for n in nodes if n.get("parent_id") == "ev_chi" and n.get("node_type") == "leaf"]
if leaves_still_on_ev_chi:
    print(f"WARNING: {len(leaves_still_on_ev_chi)} leaves still point to ev_chi after reparent", file=sys.stderr)
else:
    nodes[:] = [n for n in nodes if n.get("node_id") != "ev_chi"]

cat["nodes"] = nodes
cat["catalog_version"] = "2.65.0"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"CHI leaves before: {counts_before}")
print(f"CHI leaves kept + reparented: {kept}")
print(f"CHI duplicates removed: {removed_dup}")
print(f"total leaves now: {sum(1 for n in nodes if n.get('node_type')=='leaf')}")
print(f"sha256: {sha}")

# Partition finale
from collections import Counter
chi_now = [n for n in nodes if n.get("event")=="CHI" and n.get("node_type")=="leaf"]
by_parent = Counter(n.get("parent_id") for n in chi_now)
print(f"CHI leaves partition: {dict(by_parent)}")
chi_with_bloc = [n for n in chi_now if BLOC_MATCH_RE.search(n.get("label","") or "")]
print(f"CHI leaves still with (bloc X) marker: {len(chi_with_bloc)}")
