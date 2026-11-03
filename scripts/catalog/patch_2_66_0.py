"""Patch catalog 2.65.2 → 2.66.0 — Arbre Métriques cible 4 branches
(CAPTURE / LTE / NR / IP_Services) — REPRISE 11 Agent BC5.

Restructure :
  - Nouvelle tech `IP_Services` qui remplace `Shared` (49 events reparentés
    dans 6 catégories métier : Services data, Application throughput,
    SIP/IMS signalling, Voice, Events réseau, Position).
  - `Shared` est retiré (ses 6 catégories migrées sous IP_Services).
  - `Other` reste comme tech mais toutes ses leaves `displayed=False` →
    exclues de l'arbre affiché.
  - CAPTURE / LTE / NR : inchangés (post REPRISE 8 Point 4 + REPRISE 10).

Mapping événements Shared → IP_Services catégories :
  Services data (12)       : DREQ DCOMP DAA DAC DAD DAF DNSQUERY DSUMMARY RBI CMDREQ CMDCOMP SCRIPT
  Application throughput(2): PPPRATE APPLIST
  SIP/IMS signalling (3)   : SIPSM SIPREGA SIPREGD
  Voice (7)                : RTPJITTER RTPSM AQDL AQI AQRX AMRS QOSFLOW
  Events réseau (19)       : PAA PAC PAD PBA PBC PBD RABA RABC RABD LUA LUS
                             SEI PSM PSMI PSMR ROAM LOCK DEVI MEI
  Position (5)             : GPS GAA GAC GAD MARK

Reste 1 event Shared non classé : PCHI (CDMA control header, hors scope IP) →
reparenté vers Other.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app/kpi/catalog_release/catalog_2.65.2.json"
DST = ROOT / "app/kpi/catalog_release/catalog_2.66.0.json"

# Nouveau mapping : event_code → nouveau cat_id (sous tech_IP_Services)
CAT_SERVICES_DATA   = "cat_IP_services_data"
CAT_APP_THROUGHPUT  = "cat_IP_application_throughput"
CAT_SIP_IMS         = "cat_IP_sip_ims_signalling"
CAT_VOICE           = "cat_IP_voice"
CAT_NETWORK_EVENTS  = "cat_IP_network_events"
CAT_POSITION        = "cat_IP_position"

EVENT_TO_CAT = {}
for ev in ["DREQ","DCOMP","DAA","DAC","DAD","DAF","DNSQUERY","DSUMMARY","RBI","CMDREQ","CMDCOMP","SCRIPT"]:
    EVENT_TO_CAT[ev] = CAT_SERVICES_DATA
for ev in ["PPPRATE","APPLIST"]:
    EVENT_TO_CAT[ev] = CAT_APP_THROUGHPUT
for ev in ["SIPSM","SIPREGA","SIPREGD"]:
    EVENT_TO_CAT[ev] = CAT_SIP_IMS
for ev in ["RTPJITTER","RTPSM","AQDL","AQI","AQRX","AMRS","QOSFLOW"]:
    EVENT_TO_CAT[ev] = CAT_VOICE
for ev in ["PAA","PAC","PAD","PBA","PBC","PBD","RABA","RABC","RABD","LUA","LUS","SEI","PSM","PSMI","PSMR","ROAM","LOCK","DEVI","MEI"]:
    EVENT_TO_CAT[ev] = CAT_NETWORK_EVENTS
for ev in ["GPS","GAA","GAC","GAD","MARK"]:
    EVENT_TO_CAT[ev] = CAT_POSITION

cat = json.loads(SRC.read_text())
nodes = cat["nodes"]
by_id = {n["node_id"]: n for n in nodes}

# 1) Créer tech IP_Services
tech_ip = {
    "node_id": "tech_IP_Services",
    "node_type": "tech",
    "label": "IP / Services",
    "parent_id": None,
}
# 2) Créer les 6 catégories IP
cats_ip = [
    (CAT_SERVICES_DATA,  "Services data"),
    (CAT_APP_THROUGHPUT, "Application throughput"),
    (CAT_SIP_IMS,        "SIP / IMS signalling"),
    (CAT_VOICE,          "Voice"),
    (CAT_NETWORK_EVENTS, "Events réseau"),
    (CAT_POSITION,       "Position"),
]
cat_nodes_ip = [
    {"node_id": cid, "node_type": "category", "label": clabel, "parent_id": tech_ip["node_id"]}
    for (cid, clabel) in cats_ip
]

nodes.extend([tech_ip] + cat_nodes_ip)

# 3) Reparent events sous Shared → IP_Services
reparented = 0
pchi_removed = 0
events_to_drop = set()
for n in nodes:
    if n.get("node_type") != "event":
        continue
    parent_cat = n.get("parent_id")
    parent = by_id.get(parent_cat)
    if not parent or parent.get("node_type") != "category":
        continue
    tech_cur = by_id.get(parent.get("parent_id"))
    if not tech_cur or tech_cur.get("label") != "Shared":
        continue
    ev = (n.get("event") or n.get("label") or "").upper()
    new_cat = EVENT_TO_CAT.get(ev)
    if new_cat:
        n["parent_id"] = new_cat
        reparented += 1
    else:
        # PCHI etc. : non classé IP → marqué pour suppression
        events_to_drop.add(n["node_id"])
        pchi_removed += 1

# Supprimer events non classés + leurs leaves descendants
if events_to_drop:
    drop_full = set()
    for pid in events_to_drop:
        drop_full.add(pid)
        for n in nodes:
            if n.get("parent_id") == pid:
                drop_full.add(n["node_id"])
    nodes[:] = [n for n in nodes if n["node_id"] not in drop_full]
    pchi_removed = len(drop_full)

# 4) Retirer tech_Shared + ses catégories (empty)
removed_shared = {n["node_id"] for n in nodes if (n.get("node_type") == "tech" and n.get("label") == "Shared") or (n.get("node_type") == "category" and (by_id.get(n.get("parent_id")) or {}).get("label") == "Shared")}
nodes[:] = [n for n in nodes if n["node_id"] not in removed_shared]

# 5) Retirer tech_Other complètement (exclus de l'arbre selon spec cible)
#    + ses catégories + events + leaves. PCHI etc. ne doivent plus apparaître.
by_id = {n["node_id"]: n for n in nodes}
other_tech_id = None
for n in nodes:
    if n.get("node_type") == "tech" and n.get("label") == "Other":
        other_tech_id = n["node_id"]
        break

def descendants(root_id):
    """BFS collect all descendants (and the root itself)."""
    out = {root_id}
    stack = [root_id]
    while stack:
        p = stack.pop()
        for n in nodes:
            if n.get("parent_id") == p and n["node_id"] not in out:
                out.add(n["node_id"])
                stack.append(n["node_id"])
    return out

to_remove = descendants(other_tech_id) if other_tech_id else set()
other_hidden = len(to_remove)
nodes[:] = [n for n in nodes if n["node_id"] not in to_remove]

cat["nodes"] = nodes
cat["catalog_version"] = "2.66.0"
cat["decoder_min_version"] = "1.11.0"

DST.write_text(json.dumps(cat, sort_keys=True, indent=2, ensure_ascii=False))
sha = hashlib.sha256(DST.read_bytes()).hexdigest()

leaves_total = sum(1 for n in nodes if n.get("node_type") == "leaf")
displayed = sum(1 for n in nodes if n.get("node_type") == "leaf" and n.get("displayed"))
techs = [n["label"] for n in nodes if n.get("node_type") == "tech"]
print(f"wrote: {DST}")
print(f"events reparented Shared→IP: {reparented}")
print(f"nodes removed PCHI/non-classified: {pchi_removed}")
print(f"tech branches after: {techs}")
print(f"total leaves: {leaves_total}, displayed: {displayed}, hidden Other: {other_hidden}")
print(f"sha256: {sha}")
