"""Phase 2.2a — Génère les YAMLs décodeur depuis le CSV NFF 2.50.

Règles de section (BC3) :
- "Parameters" (toujours) : header commun, `Measured system` en col 4.
- "Parameters for LTE"    : paramètres LTE (col = 4 + field_no de section).
- "Parameters for NR"     : paramètres NR.
- "Parameters for LTE and NR" : les deux (émis sous les deux systèmes si
  l'event les porte).
- Autres sections (GSM, UMTS FDD, EVDO, cdmaOne, …) ignorées pour les
  events scope LTE/NR : elles existent dans le YAML uniquement si l'event
  est explicitement Other.

Measured system values : 7 ou 8 → LTE, 9 → NR.

Events d'état sans Measured system (HOA, CMDREQ, DAA, …) : première
section non "Parameters" à partir de col 4 (col = 4 + field_no). Pour ces
events, system_col hérité des YAMLs 1.5.1 (défaut 4).

Layouts conditionnels (PHRATE Ph. ch. type, DCOMP causes, DREQ) : non
émis en Phase 2.2a (TODO 2.2b) — le YAML garde seulement la section
principale sans discriminateur subdivisé.

Usage :
  python scripts/catalog/build_yamls.py \
    --csv /specs/nmf_all_events_fields_2.50.csv \
    --categories scripts/catalog/categories.yaml \
    --out-dir app/nmf_decoder/schemas-2.50/ \
    --legacy-schemas app/nmf_decoder/schemas/
"""
from __future__ import annotations
import argparse, csv, json, re, sys
from pathlib import Path
import yaml

CSV_TO_SCHEMA_TYPE = {
    "Integer": "int", "Float": "float", "String": "text", "Boolean": "bool",
    "Enum": "int", "Hex": "hex", "Timestamp": "text",
}
STRUCTURAL = {"#Header params", "#Cells", "Scope", "PRB index", "RB ID",
              "#Params/Serving cell", "#Params/SCell", "#Params/Neighbour",
              "Measured system"}

# Patterns structurels par label (via regex) — synchro avec audit_strict.py
import re as _re
STRUCTURAL_LABEL_RX = _re.compile(
    r"^(measured system|#header params?|#cells|#params/|scope|#antennas|#apps|#tsl results|#chs|#act set pns|#headers|#(.*) results|#(.*) sets|#ranks|#rbs|#(sym|phich|pbch|rb))",
    _re.IGNORECASE,
)

def _is_structural_label(name: str) -> bool:
    if name in STRUCTURAL: return True
    if name and name.startswith("#"): return True
    return bool(STRUCTURAL_LABEL_RX.match(name or ""))

# Rule : (event_system_set, section_name) → inclure dans YAML
# system_set : {7,8} = LTE, {9} = NR, mixte = {7,8,9}
def section_matches(event_systems: set[int], section: str) -> bool:
    s = (section or "").strip().lower()
    if s == "parameters":            return True
    if "lte and nr" in s:
        return bool(event_systems & {7, 8, 9})
    if s == "parameters for lte":
        return bool(event_systems & {7, 8})
    if s == "parameters for nr":
        return 9 in event_systems
    # Autres sections (GSM, UMTS, EVDO…) = legacy pour nous
    return False

def slugify(s: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_").lower() or "field")

def _no(r):
    try: return int(r["field_no"])
    except (TypeError, ValueError): return 999

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--categories", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--legacy-schemas", default=None,
                    help="Dir with 1.5.1 YAMLs to inherit system_col / systems per event")
    args = ap.parse_args()

    # Legacy carry-over : system_col + systems + context_count par event
    legacy_sc: dict[str, int] = {}
    legacy_sys: dict[str, list[int]] = {}
    legacy_cc: dict[str, int] = {}
    if args.legacy_schemas:
        for p in Path(args.legacy_schemas).glob("*.yaml"):
            try:
                d = json.loads(p.read_text())
                ev = d.get("event") or p.stem
                sc = d.get("system_col")
                if isinstance(sc, int): legacy_sc[ev] = sc
                sysl = d.get("systems")
                if isinstance(sysl, list): legacy_sys[ev] = sysl
                cc = d.get("context_count")
                if isinstance(cc, int): legacy_cc[ev] = cc
            except Exception:
                pass
        print(f"[build_yamls] legacy loaded: system_col={len(legacy_sc)} systems={len(legacy_sys)} context_count={len(legacy_cc)}")
    DEFAULT_SYSTEM_COL = 4

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(args.categories) as f:
        cat_cfg = yaml.safe_load(f)["events"]
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    by_event: dict[str, list] = {}
    for r in rows:
        by_event.setdefault(r["event"], []).append(r)

    produced = 0; skipped = 0
    for ev, flds in by_event.items():
        ev_cfg = cat_cfg.get(ev, {})
        if ev_cfg.get("exclude"):
            skipped += 1
            continue
        # Events `#X` sont des metadata capture-level (Capture context),
        # pas stockés en colonnes nmf_event_light. PG rejette un nom de
        # colonne commençant par `#`. On génère un YAML vide (header=[])
        # pour que source.py ignore la ligne (déjà fait via startswith('#'))
        # — pas de nouvelle colonne requise. 2.2b : exposer ces metadata
        # dans nmf_capture ou une table capture_attributes dédiée.
        if ev.startswith("#"):
            doc = {"event": ev, "spec_version": "2.50", "schema_version": "1.6.0",
                   "systems": [7], "system_col": 4, "cell_scoped": False,
                   "min_format": "2.50", "unknown_tail": "keep", "header": []}
            safe_name = ev.replace("#", "_hash_")
            (out_dir / f"{safe_name}.yaml").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
            produced += 1
            continue
        # Determine systems : 1) legacy_sys 2) default LTE (7) pour cell_scoped,
        # Shared sinon [7] pour LTE (conservateur).
        systems = legacy_sys.get(ev) or [7]
        system_set = set(systems)
        # Measured system present → system_col=4 par défaut. Sinon None.
        has_measured_sys = any((r.get("name") == "Measured system") for r in flds)
        system_col = legacy_sc.get(ev) or (DEFAULT_SYSTEM_COL if has_measured_sys else None)
        context_count = legacy_cc.get(ev, 0)
        # Base cols (reproduit schema.py first_param_col) :
        #   - "Parameters" commune : Measured system à system_col ; sinon
        #     fields partent à 4 + context_count.
        #   - "Parameters for X" : premier field à system_col+1 ; sinon à
        #     4 + context_count.
        base_common = system_col if has_measured_sys else (4 + context_count)
        base_specific = (system_col + 1) if has_measured_sys else (4 + context_count)

        headers = []
        seen_codes = set()
        flds_sorted = sorted(flds, key=lambda r: (
            0 if (r["section"] or "").strip().lower() == "parameters" else 1,
            r["section"] or "", _no(r)
        ))
        for row in flds_sorted:
            section = row["section"] or ""
            name = row["name"]
            if _is_structural_label(name): continue
            if not section_matches(system_set, section): continue
            fno = _no(row)
            if section.strip().lower() == "parameters":
                col_abs = base_common + fno - 1
            else:
                col_abs = base_specific + fno - 1
            code = f"{ev.lower()}.{slugify(name)}"
            # Dédup : si une section LTE et NR partage un field, on garde la 1ère.
            if code in seen_codes: continue
            seen_codes.add(code)
            h = {
                "col": col_abs,
                "code": code,
                "label": name,
                "section": section,
                "type": CSV_TO_SCHEMA_TYPE.get(row.get("type", "").strip(), "text"),
                "unit": row.get("unit") or None,
                "proof": f"NFF 2.50 {ev} {section} #{fno}",
                "agg": "mean" if row.get("type", "") == "Float" else "last",
                "metric": True,
                "category": ev_cfg.get("category") or "Unclassified",
            }
            # Décodeur attend `range` comme list [lo, hi] si présente. Omettre
            # la clé plutôt que None pour éviter le TypeError sur unpack.
            # TODO 2.2b : parser "a – b" / "a..b" du CSV pour les bornes.
            headers.append(h)
        doc = {
            "event": ev,
            "spec_version": "2.50",
            "schema_version": "1.6.0",
            "systems": systems,
            "system_col": system_col,
            "context_count": context_count,  # carry-over 1.5.1 pour effective_col
            "cell_scoped": bool(ev_cfg.get("cell_scoped", False)),
            "min_format": "2.50",
            "unknown_tail": "keep",
            "header": headers,
        }
        safe_name = ev.replace("#", "_hash_").replace("/", "_")
        (out_dir / f"{safe_name}.yaml").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        produced += 1
    print(f"[build_yamls] produced={produced} skipped={skipped} out={out_dir}")

if __name__ == "__main__":
    main()
