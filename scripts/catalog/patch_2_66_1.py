"""Patch catalog 2.66.0 → 2.66.1 — REPRISE 12 Point 2 fix non-perte.

Problème : patch_2_66_0.py a retiré tech_Other complet, perdant 10 leaves
avec valeurs : chi_max_tx_power (ev_chi_other, CHI LTE), luf_luf_status,
luf_old_lac, tua_tau_type, tuf_emm_cause, tus_mcc, tus_mnc, tus_tac,
rrre_re_est_cause, rrre_re_est_status.

Fix : repartir de 2.66.0 et restaurer sous la bonne branche depuis 2.65.2 :
  - events CHI (ev_chi_other) : les champs chi_* restants (max_tx_power etc)
    rejoignent ev_chi_lte (branche LTE > Signalling) — car champs LTE légitimes.
  - events LUA/LUF/LUS/TUA/TUF/TUS/RRRE/SEI : rejoignent IP > Events réseau.

Sortie : `app/kpi/catalog_release/catalog_2.66.1.json` + sha256.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_265 = ROOT / "app/kpi/catalog_release/catalog_2.65.2.json"
SRC_266 = ROOT / "app/kpi/catalog_release/catalog_2.66.0.json"
DST     = ROOT / "app/kpi/catalog_release/catalog_2.66.1.json"

# Events dont les leaves doivent être restaurés
# ev_chi_other → absorber vers ev_chi_lte (LTE Signalling)
# ev_* réseau → IP Events réseau cat_IP_network_events
CHI_LTE_MERGE = {"ev_chi_other"}  # merge en ev_chi_lte
IP_NETWORK_EVENTS = {
    "ev_luf", "ev_lua", "ev_lus",
    "ev_tua", "ev_tuf", "ev_tus",
    "ev_rrre",
    "ev_sei",
}

c265 = json.loads(SRC_265.read_text())
c266 = json.loads(SRC_266.read_text())
by_id_265 = {n["node_id"]: n for n in c265["nodes"]}
by_id_266 = {n["node_id"]: n for n in c266["nodes"]}

restored_leaves = 0
restored_events = 0

# Trouver cat_IP_network_events (créé par 2.66.0)
cat_ip_net = next((n for n in c266["nodes"] if n.get("node_id") == "cat_IP_network_events"), None)
ev_chi_lte = next((n for n in c266["nodes"] if n.get("node_id") == "ev_chi_lte"), None)
if not cat_ip_net or not ev_chi_lte:
    raise RuntimeError("expected categories missing in 2.66.0")

# Pour chaque event à restaurer : prendre son node + leaves depuis 2.65.2
for ev_id in sorted(CHI_LTE_MERGE | IP_NETWORK_EVENTS):
    ev_node_265 = by_id_265.get(ev_id)
    if not ev_node_265:
        continue
    if ev_id in CHI_LTE_MERGE:
        # Pour CHI legacy (chi_max_tx_power etc) : reparent les leaves vers ev_chi_lte
        target_event_id = "ev_chi_lte"
    else:
        # Pour LUA/LUF/LUS/TUA/.../RRRE/SEI : ajouter l'event sous cat_IP_network_events
        new_event = dict(ev_node_265)
        new_event["parent_id"] = "cat_IP_network_events"
        if not any(n.get("node_id") == ev_id for n in c266["nodes"]):
            c266["nodes"].append(new_event)
            restored_events += 1
        target_event_id = ev_id
    # Reparent les leaves de cet event
    for n in c265["nodes"]:
        if n.get("parent_id") == ev_id and n.get("node_type") == "leaf":
            # Vérifier qu'elle n'existe pas déjà dans 2.66.0
            if any(x.get("node_id") == n["node_id"] for x in c266["nodes"]):
                continue
            new_leaf = dict(n)
            new_leaf["parent_id"] = target_event_id
            c266["nodes"].append(new_leaf)
            restored_leaves += 1

c266["catalog_version"] = "2.66.1"
DST.write_text(json.dumps(c266, sort_keys=True, indent=2, ensure_ascii=False))

sha = hashlib.sha256(DST.read_bytes()).hexdigest()
print(f"wrote: {DST}")
print(f"events restored: {restored_events}")
print(f"leaves restored: {restored_leaves}")
print(f"total leaves after: {sum(1 for n in c266['nodes'] if n.get('node_type') == 'leaf')}")
print(f"sha256: {sha}")
