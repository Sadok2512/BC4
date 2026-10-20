"""Décodeur 1.1.0 P2 — assigne la ``category`` sur chaque champ metric-able.

14 catégories (ordre & nommage mission) :
  radio_serving · neighbours · throughput_layers · link_quality ·
  allocation_mcs · csi · mimo_port · ul_power · voice · services ·
  position · signalling_states · session · terminal_cell

Heuristique sur le ``code`` + ``label`` du champ (match le plus spécifique
gagne). Un champ non classé reçoit ``category: "unknown"`` → listé dans
le rapport pour revue manuelle.

Scope : les 19 YAMLs ``schemas/`` et les 68 YAMLs ``schemas-pending/``.
Les champs sont enrichis d'un attribut ``category`` ; aucun autre champ
n'est modifié. Idempotent (relancer réaffecte).
"""
from __future__ import annotations

import json
from pathlib import Path
import re


REPO = Path(__file__).resolve().parent.parent
LIVE_SCHEMAS_DIR = REPO / "app" / "nmf_decoder" / "schemas"
PENDING_SCHEMAS_DIR = REPO / "app" / "nmf_decoder" / "schemas-pending"


CATEGORIES = (
    "radio_serving",
    "neighbours",
    "throughput_layers",
    "link_quality",
    "allocation_mcs",
    "csi",
    "mimo_port",
    "ul_power",
    "voice",
    "services",
    "position",
    "signalling_states",
    "session",
    "terminal_cell",
)


def _category_for(event: str, code: str, label: str, group: str | None) -> str:
    """Choisit la catégorie du champ (plus spécifique en premier)."""
    ev = event.upper()
    c = code.lower()
    l = label.lower()

    # Session state machines
    if ev in {"RRCSM", "SIPSM", "L3SM", "RTPSM"}:
        return "session"
    # Signalling states (événements d'état/action radio)
    if ev in {"RRA", "RRC", "RRD", "GAA", "GAC", "GAD", "PBA", "PBC", "PBD",
              "CREL", "MEI", "NLIST", "SEI", "ROAM", "LOCK", "MARK", "PCHI",
              "HOI", "RACHI", "HOA", "HOS",
              "CAA", "CAC", "CAD",  # Call attempt / complete / detach
              "PAA", "PAC", "PAD"}:  # Packet attach / complete / detach
        return "signalling_states"
    # CHI = Channel Info (configuration PHY) → terminal_cell
    if ev == "CHI":
        return "terminal_cell"
    # Voice
    if ev in {"AQDL", "AQRX", "AQI", "VOIPI", "RTPJITTER", "PPPRATE", "AMRS", "FER"}:
        return "voice"
    # Services / app
    if ev in {"DRATE", "DNSQUERY", "DAA", "DAC", "DAD", "DREQ", "DCOMP",
              "SIPREGA", "SIPREGC", "SIPREGD"} or "app_" in c or "dns" in c:
        return "services"
    # Position
    if ev == "GPS" or "lat" in c or "lon" in c or "position" in c:
        return "position"
    # Terminal / cell meta (headers de fichier + cell_type/band/channel/pci)
    if ev.startswith("#"):
        return "terminal_cell"
    if "cell_type" in c or "cell_band" in c or "cell_ch" in c or "cell_pci" in c:
        return "terminal_cell"

    # Serving / neighbours : CELLMEAS header = serving, CELLMEAS cells group = neighbours
    if ev in {"CELLMEAS", "CI"}:
        if ("rsrp" in c or "rsrq" in c or "rssi" in c or "snr" in c or "sinr" in c
                or "pathloss" in c or "timing" in c):
            return "radio_serving" if group is None else "neighbours"
        if group is not None and (
            "cell_type" in c or "cell_band" in c or "cell_ch" in c or "cell_pci" in c
            or "cell.type" in c or "cell.band" in c or "cell.ch" in c or "cell.pci" in c
        ):
            return "neighbours"
    # Neighbours
    if ev == "CELLSCAN" or ev == "ANRI" or "neighbour" in l or "neighbor" in l:
        return "neighbours"
    # Compteurs / discriminants / meta decoder (#hdr_n, #n_cells, params_*)
    if "hdr_n" in c or c.endswith(".n_cells") or ".params_" in c or ".n_" in c:
        return "terminal_cell"
    # Sample duration & #Header params
    if "sample_duration" in c or "duration" == c.split(".")[-1]:
        return "terminal_cell"
    # MIMO per antenna port
    if ev == "MIMOMEAS":
        return "mimo_port"
    # CSI (channel state info)
    if ev == "CQI" or "pmi" in c or "ri" in c or "subband" in l or "wideband" in l:
        return "csi"
    # Throughput par couche (prefix décodeur : app_, mac_, rlc_, pdcp_, pdsch_, pusch_)
    if "bitrate" in c or "throughput" in l.lower() or "thrpt" in c:
        return "throughput_layers"
    # BLER / modulation / HARQ / retx
    if "bler" in c or "retx" in c or "harq" in c or "fer" in c or "mod" in c:
        return "link_quality"
    # Allocation MCS / rank / PRB
    if "mcs" in c or "rank" in c or "prb" in c or "tbs" in c or "allocation" in l:
        return "allocation_mcs"
    # UL power
    if ev == "TXPC" or "tx_power" in c or "power_headroom" in c or "pucch" in c or "pusch" in c:
        return "ul_power"
    # Blocks (PHY/MAC/RLC/PDCP activité couche) → link_quality
    if "block_rate" in c or "new_blocks" in c or "blocks_rb" in c:
        return "link_quality"
    # Radio bearer id, channel type → terminal_cell (identité)
    if "rb_id" in c or "ph_ch_type" in c:
        return "terminal_cell"
    # CFI (Control Format Indicator), percentage distribution dans PLAID/PLAIU → allocation_mcs
    if "cfi" in c or (ev in {"PLAID", "PLAIU"} and "percentage" in c):
        return "allocation_mcs"
    # ci.port = port d'antenne
    if ev == "CI" and ".port" in c:
        return "mimo_port"
    # TAD = Timing Advance → radio_serving
    if ev == "TAD" or ".ta" == c[-3:]:
        return "radio_serving"

    return "unknown"


def _enrich(schema: dict) -> tuple[int, int]:
    """Assigne ``category`` sur chaque champ. Retourne (assigned, unknown)."""
    event = schema.get("event", "")
    assigned = 0
    unknown = 0
    for f in schema.get("header", []) or []:
        cat = _category_for(event, f.get("code") or "", f.get("label") or "", None)
        f["category"] = cat
        assigned += 1
        if cat == "unknown":
            unknown += 1
    for g in schema.get("groups", []) or []:
        gname = g.get("name")
        for f in g.get("fields", []) or []:
            cat = _category_for(event, f.get("code") or "", f.get("label") or "", gname)
            f["category"] = cat
            assigned += 1
            if cat == "unknown":
                unknown += 1
    return assigned, unknown


def main() -> None:
    reports: list[tuple[str, int, int, str]] = []
    for src in (LIVE_SCHEMAS_DIR, PENDING_SCHEMAS_DIR):
        for path in sorted(src.glob("*.yaml")):
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            assigned, unknown = _enrich(schema)
            path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            location = "live" if src is LIVE_SCHEMAS_DIR else "pending"
            reports.append((path.stem, assigned, unknown, location))

    total_assigned = sum(r[1] for r in reports)
    total_unknown = sum(r[2] for r in reports)
    print(f"YAMLs enrichis       : {len(reports)}")
    print(f"Champs catégorisés   : {total_assigned}")
    print(f"Champs unknown       : {total_unknown}")
    print()
    print("Unknown par événement :")
    for event, _assigned, unk, loc in sorted(reports, key=lambda r: -r[2]):
        if unk > 0:
            print(f"  {event:14s} [{loc}]  unknown={unk}")


if __name__ == "__main__":
    main()
