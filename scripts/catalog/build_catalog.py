"""Phase 1 — Générateur catalogue 2.50.X depuis CSV spec.

Usage :
  docker exec -w /app bc4-api-1 python scripts/catalog/build_catalog.py \
      --csv /specs/nmf_all_events_fields_2.50.csv \
      --version 2.50.1 \
      --decoder-min 1.6.0 \
      --out app/kpi/catalog_release/catalog_2.50.1.json

Lit le CSV `event,section,field_no,name,type,unit,range,description`
→ produit un JSON `catalog_<version>.json` + une ligne dans
`catalog_release` (sha256 recalculé, is_current=TRUE).

Hiérarchie (initiale, raffinée en Phase 1 bis par la table enum
`nemo_file_format_2.50.txt`) :
  Technology ∈ {LTE, NR, Shared}
    └── Category (inféré depuis event ou section)
        └── Event
            └── Field (= leaf)
              - metric_id = `<event>.<field_slug>`  (slug = name lower + _)
              - type / unit / range / description = CSV

Exclusions documentées (listées dans le JSON) :
  - `#Header params`, `#Cells`, `#Params/...`, `Scope`, `PRB index`, `RB ID`
    = attributs structurels, pas feuilles.
  - identités (#EI, #SI, IMSI/IMEI/TMSI/GUTI) masquées (règle identité).
  - payloads hex (stockés en stg_event).

Toute feuille non consommable (ex. "Payload" hex) marquée `selectable=false`,
grisée côté UI avec tooltip (jamais cachée — règle BC3).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sqlalchemy import text  # noqa: E402
from app.db import SessionLocal  # noqa: E402

# Patterns de catégorisation hiérarchique (règles explicites,
# refinables par un fichier spec séparé en Phase 1 bis).
TECH_LTE = {"PHRATE", "MACRATE", "PLAID", "PLAIU", "CELLMEAS", "RRC", "CQI",
            "DCI", "TAD", "CI", "RACHSM", "RRA", "RRC", "RRD", "RRF",
            "HOA", "HOI", "HOS", "L3SM", "RRCSM", "SIPSM", "RTPSM",
            "MIMOMEAS", "TXPC", "DRATE", "PDCPRATED", "PDCPRATEU",
            "RLCRATE", "RLCRATEU", "MACI", "MACRATEU", "PLAISUM", "ROHC"}
TECH_NR = set()  # NR events détectés par discriminator Scope (field) dans CSV
TECH_SHARED = {"GPS", "MARK", "SCRIPT", "CMDREQ", "CMDCOMP", "DAA", "DREQ",
               "DCOMP", "DAC", "DAD", "DAF", "APPLIST", "LOCK", "ROAM",
               "DEVI", "PSM", "PSMR", "PSMI", "LUA", "LUS", "SEI",
               "GAA", "GAC", "GAD", "PAA", "PAC", "PAD", "PBA", "PBC",
               "PBD", "CAA", "CAC", "CAD", "RABA", "RABC", "RABD",
               "SIPREGA", "SIPREGC", "SIPREGD", "DNSQUERY", "DSUMMARY",
               "RTPJITTER", "FER", "AMRS", "AQDL", "AQI", "AQRX", "CHI",
               "RACHI", "NLIST", "QOSFLOW", "BSR", "PCHI"}

EXCLUDE_FIELDS = {
    "#Header params", "#Cells", "Scope", "PRB index", "RB ID",
    "#EI", "#SI", "IMSI", "IMEI", "TMSI", "GUTI",
    "cmd_index", "action_index", "req_index",
    "Payload",
}

def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_").lower()
    return s or "field"

def classify_tech(event: str, section: str | None) -> str:
    if event in TECH_LTE: return "LTE"
    if event in TECH_NR: return "NR"
    if event in TECH_SHARED: return "Shared"
    if section and "NR" in (section or "").upper(): return "NR"
    return "LTE"  # défaut conservateur pour LTE-first corpus

def classify_category(event: str, section: str | None) -> str:
    s = (section or "").strip() or "Unspecified"
    # Normaliser quelques sections NFF 2.50 vers nos buckets UI.
    MAP = {
        "Parameters": "Capture context",
        "Serving cell measurements": "Serving radio",
        "Neighbor cells": "Neighbours",
        "Carrier aggregation": "Carrier aggregation",
        "Throughput": "Throughput per layer",
        "Allocation": "Allocation & MCS",
        "Channel quality": "Link quality",
        "MIMO": "MIMO per port",
        "GPS": "Position",
        "Services": "Services (tasks)",
        "Scanner": "Scanner",
        "Signalling": "Signalling",
        "Events": "Events ⚑",
    }
    for k, v in MAP.items():
        if k.lower() in s.lower(): return v
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--version", required=True, help="2.50.1, 2.50.2, ...")
    ap.add_argument("--decoder-min", required=True, help="e.g. 1.6.0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec-version", default=None, help="defaults to major.minor from --version")
    ap.add_argument("--commit", action="store_true", help="insert into catalog_release")
    args = ap.parse_args()

    spec_v = args.spec_version or ".".join(args.version.split(".")[:2])

    # 1) parse CSV
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[build_catalog] CSV loaded: rows={len(rows)}")
    events = sorted({r["event"] for r in rows})
    print(f"[build_catalog] distinct events={len(events)}")

    # 2) build hierarchical nodes
    categories: dict[tuple[str, str], dict] = {}  # (tech, cat) → cat node
    event_nodes: dict[tuple[str, str, str], dict] = {}  # (tech, cat, event)
    leaves: list[dict] = []
    excluded: list[dict] = []

    for r in rows:
        ev, name, sec = r["event"], r["name"], r.get("section")
        tech = classify_tech(ev, sec)
        cat = classify_category(ev, sec)
        if name in EXCLUDE_FIELDS or ev.startswith("#"):
            excluded.append({"event": ev, "field": name, "reason": "structural_or_identity"})
            continue
        cat_key = (tech, cat)
        if cat_key not in categories:
            categories[cat_key] = {
                "node_type": "category", "tech": tech, "label": cat,
                "node_id": f"cat_{tech}_{slugify(cat)}", "parent_id": f"tech_{tech}",
            }
        ev_key = (tech, cat, ev)
        if ev_key not in event_nodes:
            event_nodes[ev_key] = {
                "node_type": "event", "label": ev, "event": ev,
                "node_id": f"ev_{slugify(ev)}", "parent_id": categories[cat_key]["node_id"],
            }
        leaves.append({
            "node_type": "leaf", "event": ev, "label": name,
            "metric_id": f"{ev}.{slugify(name)}",
            "field_no": r.get("field_no"), "type": r.get("type"),
            "unit": r.get("unit") or None, "range": r.get("range") or None,
            "description": r.get("description") or None,
            "parent_id": event_nodes[ev_key]["node_id"],
            "node_id": f"lf_{slugify(ev)}_{slugify(name)}",
            "selectable": True, "n": 0,
            "proof": "documented-2.50",
        })

    tech_nodes = [{"node_type": "tech", "label": t, "node_id": f"tech_{t}",
                   "parent_id": None} for t in sorted({tech for tech, _ in categories.keys()})]
    nodes = tech_nodes + list(categories.values()) + list(event_nodes.values()) + leaves
    n_categories = len(categories); n_events = len(event_nodes); n_leaves = len(leaves)
    print(f"[build_catalog] tech={len(tech_nodes)} categories={n_categories} events={n_events} leaves={n_leaves} excluded={len(excluded)}")

    payload = {
        "catalog_version": args.version,
        "spec_version": spec_v,
        "decoder_min_version": args.decoder_min,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "source_csv": args.csv,
        "n_categories": n_categories,
        "n_events": n_events,
        "n_leaves": n_leaves,
        "nodes": nodes,
        "excluded": excluded,
    }

    # 3) write JSON (deterministic : sort keys)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"[build_catalog] out={out_path} sha256={sha}")

    # 4) register in DB (optional)
    if args.commit:
        db = SessionLocal()
        try:
            db.execute(text("UPDATE catalog_release SET is_current=FALSE WHERE is_current=TRUE"))
            db.execute(text(
                "INSERT INTO catalog_release(version, spec_version, decoder_min_version, "
                "sha256, n_categories, n_metrics, n_leaves, changelog, is_current) "
                "VALUES(:v, :s, :d, :sha, :nc, :nm, :nl, :cl, TRUE) "
                "ON CONFLICT(version) DO UPDATE SET sha256=excluded.sha256, "
                "n_categories=excluded.n_categories, n_metrics=excluded.n_metrics, "
                "n_leaves=excluded.n_leaves, is_current=TRUE"
            ), {"v": args.version, "s": spec_v, "d": args.decoder_min, "sha": sha,
                "nc": n_categories, "nm": n_events, "nl": n_leaves,
                "cl": f"generated from {args.csv}"})
            db.commit()
            print(f"[build_catalog] catalog_release row written : version={args.version} is_current=TRUE")
        finally:
            db.close()

if __name__ == "__main__":
    main()
