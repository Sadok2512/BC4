"""Phase 2.1/2.2a — Génère les 282 YAML décodeur depuis le CSV NFF 2.50.

Format compatible avec le decoder : `col` = INDEX ABSOLU de token dans la
ligne NMF brute. Correction 2.2a : `col = system_col + field_no` (où
`field_no` est l'index relatif 1..N dans le CSV spec, et `system_col`
est hérité des YAMLs 1.5.1 — défaut 4 pour les events nouveaux).

Usage :
  python scripts/catalog/build_yamls.py \
    --csv /specs/nmf_all_events_fields_2.50.csv \
    --categories scripts/catalog/categories.yaml \
    --out-dir app/nmf_decoder/schemas-2.50/ \
    --legacy-schemas app/nmf_decoder/schemas/
"""
from __future__ import annotations
import argparse, csv, re
from pathlib import Path
import yaml
import json

CSV_TO_SCHEMA_TYPE = {
    "Integer": "int", "Float": "float", "String": "text", "Boolean": "bool",
    "Enum": "int", "Hex": "hex", "Timestamp": "text",
}
STRUCTURAL = {"#Header params", "#Cells", "Scope", "PRB index", "RB ID",
              "#Params/Serving cell", "#Params/SCell", "#Params/Neighbour"}

def slugify(s: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_").lower() or "field")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--categories", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--legacy-schemas", default=None,
                    help="Dir with 1.5.1 YAMLs to inherit system_col per event")
    args = ap.parse_args()
    # Load system_col from legacy YAMLs for carry-over
    legacy_system_col: dict[str, int] = {}
    if args.legacy_schemas:
        for p in Path(args.legacy_schemas).glob("*.yaml"):
            try:
                d = json.loads(p.read_text())
                sc = d.get("system_col")
                if isinstance(sc, int):
                    legacy_system_col[d.get("event") or p.stem] = sc
            except Exception:
                pass
        print(f"[build_yamls] legacy system_col loaded for {len(legacy_system_col)} events")
    DEFAULT_SYSTEM_COL = 4
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(args.categories) as f:
        cfg = yaml.safe_load(f)["events"]
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    by_event: dict[str, list] = {}
    for r in rows:
        by_event.setdefault(r["event"], []).append(r)

    produced = 0
    for ev, flds in by_event.items():
        ev_cfg = cfg.get(ev, {})
        if ev_cfg.get("exclude"):
            continue  # #EI / #SI identité : pas de YAML (décodeur ignore)
        cell_scoped = bool(ev_cfg.get("cell_scoped", False))
        # Ordre par field_no (int si possible, sinon 999)
        def _no(r):
            try: return int(r["field_no"])
            except (TypeError, ValueError): return 999
        flds = sorted(flds, key=_no)
        # Carry-over du system_col depuis les YAMLs 1.5.1 (sinon défaut 4).
        system_col = legacy_system_col.get(ev, DEFAULT_SYSTEM_COL)
        # Default agg declaration : last / mean / max / sum selon type/unit
        def _agg(row):
            t = (row.get("type") or "").lower(); u = (row.get("unit") or "").lower()
            if t in ("string", "text"): return "last"
            if "/s" in u or u in ("mbit/s", "kbit/s", "bytes", "bit", "packet"): return "sum"
            if row["name"].lower() in ("sample duration",): return "sum"
            if "duration" in row["name"].lower() or "elapsed" in row["name"].lower(): return "max"
            if "cqi" in row["name"].lower(): return "mean_weighted"
            return "mean"
        headers = []
        for r in flds:
            name = r["name"]
            if name in STRUCTURAL: continue
            # col absolu = system_col + field_no CSV (1-based).
            headers.append({
                "col": system_col + _no(r),
                "code": f"{ev.lower()}.{slugify(name)}" if ev else slugify(name),
                "label": name,
                "type": CSV_TO_SCHEMA_TYPE.get(r.get("type", "").strip(), "text"),
                "unit": r.get("unit") or None,
                "range": r.get("range") or None,
                "proof": f"NFF 2.50 {ev} #{r.get('field_no')}",
                "agg": _agg(r),
                "metric": True,
                "category": ev_cfg.get("category") or "Unclassified",
            })
        doc = {
            "event": ev,
            "spec_version": "2.50",
            "schema_version": "1.6.0",
            "systems": [7],  # TODO raffiner par event
            "system_col": system_col,
            "cell_scoped": cell_scoped,
            "min_format": "2.50",
            "unknown_tail": "keep",
            "header": headers,
        }
        safe_name = ev.replace("#", "_hash_").replace("/", "_")
        (out_dir / f"{safe_name}.yaml").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        produced += 1
    print(f"[build_yamls] produced={produced} out={out_dir}")

if __name__ == "__main__":
    main()
