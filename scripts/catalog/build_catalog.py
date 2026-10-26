"""Phase 1 bis — Générateur catalogue NFF 2.50.

Pipeline :
  (A) CSV nmf_all_events_fields_2.50.csv → fields par event.
  (B) categories.yaml → map event → (tech, category, cell_scoped, exclude?, mask?).
  (C) nemo_file_format_2.50.txt → enums : cell types / bands / causes.
  (D) corpus DB → cell_type présents par event (feuilles cellule créées pour
      les cell_type réellement vus ; les autres déclarées non-affichées).
  (E) hiérarchie Tech → 17 catégories → Event → (feuilles cellule | feuille
      bare field) ; toute entrée non classée → catégorie "Unclassified" visible.
  (F) JSON déterministe + sha256 ; row catalog_release (is_current=TRUE).

Usage :
  python scripts/catalog/build_catalog.py \
    --csv /specs/nmf_all_events_fields_2.50.csv \
    --txt /specs/nemo_file_format_2.50.txt \
    --categories scripts/catalog/categories.yaml \
    --version 2.50.2 --decoder-min 1.6.0 \
    --out app/kpi/catalog_release/catalog_2.50.2.json --commit
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402
from sqlalchemy import text  # noqa: E402
from app.db import SessionLocal  # noqa: E402
# 2.51.1 — source_column tirée des YAMLs du décodeur, jamais inventée.
from app.nmf_decoder.schema import schemas, column as _dec_column  # noqa: E402

CATEGORIES = [
    "Serving radio", "Neighbours", "Carrier aggregation",
    "Throughput per layer", "Link quality", "Allocation & MCS",
    "CSI", "UL power", "MIMO per port", "Beams NR", "Voice",
    "Services (tasks)", "Position", "Events ⚑", "Signalling",
    "Capture context", "Scanner", "Unclassified",
]
STRUCTURAL_FIELDS = {
    "#Header params", "#Cells", "Scope", "PRB index", "RB ID",
    "#Params/Serving cell", "#Params/SCell", "#Params/Neighbour",
}
IDENTITY_FIELDS = {"IMSI", "IMEI", "TMSI", "GUTI", "#EI", "#SI"}
MASKED_INDEX_FIELDS = {"cmd_index", "action_index", "req_index"}
PAYLOAD_FIELDS = {"Payload", "payload_b64", "Message"}

def slugify(s: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_").lower() or "field")


def _normalize_label(s: str | None) -> str:
    """Normalise un label CSV pour match avec un label YAML."""
    if not s:
        return ""
    s2 = s.strip().lower()
    s2 = re.sub(r"[^a-z0-9]+", "", s2)
    return s2


def _build_source_column_map() -> dict[tuple[str, str], str]:
    """Pour chaque (event, label_normalized_CSV), retourne la colonne
    `nmf_event_light`/`_group` dérivée du YAML du décodeur.

    L'index est double :
    - label normalisé (ex "rsrp") → colonne (ex "cell_rsrp" pour CELLMEAS)
    - code sans préfixe event (ex "cellmeas_rsrp" → "cell_rsrp")

    Chaque event du décodeur a ses headers + fields de groupes. On mappe
    les deux via `_dec_column(field.code)`. Pour un même event, un même
    label peut apparaître dans plusieurs sections (ex CELLMEAS 'RSRP'
    header + 'RSRP' group) ; on garde le premier avec un code non vide.
    """
    out: dict[tuple[str, str], str] = {}
    for ev, s in schemas().items():
        if not isinstance(s, dict):
            continue
        def _collect(schema):
            for f in schema.get("header", []) or []:
                col = _dec_column(f.get("code") or "")
                if not col:
                    continue
                lbl = _normalize_label(f.get("label") or f.get("code"))
                if lbl and (ev, lbl) not in out:
                    out[(ev, lbl)] = col
            for g in schema.get("groups", []) or []:
                for f in g.get("fields", []) or []:
                    col = _dec_column(f.get("code") or "")
                    if not col:
                        continue
                    lbl = _normalize_label(f.get("label") or f.get("code"))
                    if lbl and (ev, lbl) not in out:
                        out[(ev, lbl)] = col
        _collect(s)
        for variant in (s.get("_variants") or {}).values():
            _collect(variant)
    return out


# Index unique construit une fois (schemas() est lru_cache).
_SOURCE_COLUMN_INDEX: dict[tuple[str, str], str] = {}


def source_column_for(event: str, field_name: str) -> str:
    """Retourne la colonne `nmf_event_light` ou `_light_group` pour un
    couple (event, label CSV). Chaîne vide si aucun match YAML.
    """
    global _SOURCE_COLUMN_INDEX
    if not _SOURCE_COLUMN_INDEX:
        _SOURCE_COLUMN_INDEX = _build_source_column_map()
    key = (event.lstrip("#"), _normalize_label(field_name))
    return _SOURCE_COLUMN_INDEX.get(key, "")

def parse_enums(txt_path: Path) -> dict:
    """Extrait les enums (Cell type SCell N, Band 70NNN, ...) du spec text.
    Retourne dict {enum_name: [{value: int, label: str}, ...]}.
    """
    enums = defaultdict(list)
    text_lines = txt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    # Patterns courants : "70001 = LTE FDD 2100 band 1" ou "0 = PCell"
    enum_pat = re.compile(r"^\s{10,}(\d+)\s*=\s*(.+?)\s*$")
    current = None
    for line in text_lines:
        s = line.strip()
        if "Cell type" in s and "Integer" in line:
            current = "cell_type_lte_scell"
            continue
        if "Band" in s and "SCell band" in s:
            current = "band_lte"
            continue
        m = enum_pat.match(line)
        if m and current:
            try:
                enums[current].append({"value": int(m.group(1)), "label": m.group(2)})
            except ValueError:
                pass
        elif current and not m and s and not line.startswith("    "):
            current = None  # end of enum block
    # LTE cell types : add 0=PCell + 10+ measurement contexts hardcoded (NFF 2.50 §Cell type)
    enums["cell_type_lte_mesure"] = [
        {"value": 0, "label": "PCell"}, {"value": 1, "label": "Listed neighbour"},
        {"value": 2, "label": "Detected neighbour"}, {"value": 3, "label": "Scanner"},
        {"value": 4, "label": "Scanner neighbour"},
    ]
    enums["cell_type_nr"] = [
        {"value": 0, "label": "PCell"}, {"value": 199, "label": "SCG PSCell"},
    ] + [{"value": i, "label": f"SCell {i}"} for i in range(1, 32)] \
      + [{"value": 100 + i, "label": f"SCG SCell {i}"} for i in range(0, 32)] \
      + [{"value": 1000, "label": "Listed NR neighbour"},
         {"value": 1001, "label": "Detected NR neighbour"},
         {"value": 1002, "label": "Scanner NR neighbour"}]
    return dict(enums)

def corpus_cell_types(db) -> dict[str, set[int]]:
    """GROUP BY event, cell_type sur nmf_event_light / nmf_event_light_group.
    Retourne {event_code: {cell_type_int, ...}}. Les events sans discriminator
    cellule renvoient set() (feuille bare).

    1.7.0 — Les cell_type NR (CELLMEAS, MIMOMEAS) sont dans les groupes
    `cells`/`measurements` (nmf_event_light_group.cell_type), pas dans
    `dimension` du bucket Light. On agrège les 2 sources.
    """
    out: dict[str, set[int]] = defaultdict(set)
    # (1) dimension header (TAD/TXPC/PHRATE/PLAID + variants LTE).
    rows = db.execute(text("""
        SELECT event_code, dimension FROM nmf_event_light
        WHERE dimension IS NOT NULL AND dimension ~ '\\.cell_type=[0-9]+'
        GROUP BY event_code, dimension
    """)).all()
    pat = re.compile(r"\.cell_type=(\d+)")
    for ev, dim in rows:
        m = pat.search(dim or "")
        if m:
            out[ev].add(int(m.group(1)))
    # (2) group cell_type (CELLMEAS LTE+NR, MIMOMEAS LTE+NR via mimo_cell_type).
    rows2 = db.execute(text("""
        SELECT l.event_code, g.cell_type FROM nmf_event_light_group g
        JOIN nmf_event_light l ON l.project_id=g.project_id AND l.capture_id=g.capture_id AND l.seq=g.seq
        WHERE g.cell_type IS NOT NULL AND g.group_name IN ('cells','measurements')
        GROUP BY l.event_code, g.cell_type
    """)).all()
    for ev, ct in rows2:
        if ct is not None:
            try: out[ev].add(int(ct))
            except (TypeError, ValueError): pass
    return dict(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--txt", required=True)
    ap.add_argument("--categories", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--decoder-min", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec-version", default=None)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    spec_v = args.spec_version or ".".join(args.version.split(".")[:2])

    # (A) CSV
    with open(args.csv, newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    print(f"[build] csv_rows={len(csv_rows)}")
    all_events = sorted({r["event"] for r in csv_rows})
    print(f"[build] distinct_events_csv={len(all_events)}")

    # (B) categories.yaml
    with open(args.categories) as f:
        cat_doc = yaml.safe_load(f)
    classified = {ev: cfg for ev, cfg in cat_doc["events"].items()}
    default_tech = cat_doc.get("default_tech", "Other")
    default_category = cat_doc.get("default_category", "Legacy UMTS/CDMA/DVB")
    print(f"[build] categorised={len(classified)} default_tech={default_tech!r} default_cat={default_category!r}")

    # (C) enums
    enums = parse_enums(Path(args.txt))
    print(f"[build] enums={ {k: len(v) for k, v in enums.items()} }")

    # (D) corpus coverage — 2.51.1+ : SUPPRIMÉ du build pour garantir
    # un sha reproductible. Les cell_types "observés" sont évalués
    # RUNTIME dans `app/kpi/metrics_catalog_v4.py` (nmf_event_light_group).
    # Toutes les 7 feuilles canoniques (@cell_type) sont marquées
    # `displayed=True` dans le JSON ; le filtre selectable/grisé est
    # produit par metrics_catalog_v4 à l'enveloppe /metrics.
    cell_coverage: dict[str, set[int]] = {}

    # (E) hiérarchie
    nodes = []
    tech_nodes = {t: {"node_type": "tech", "node_id": f"tech_{t}", "label": t,
                      "parent_id": None, "collapsed_default": (t == "Other")}
                  for t in ("LTE", "NR", "Shared", "Other")}
    nodes.extend(tech_nodes.values())
    cat_nodes = {}
    event_nodes = {}
    leaves_cell = []
    leaves_bare = []
    excluded_events = []
    unclassified_events = []
    exclude_fields_total = 0

    fields_by_event = defaultdict(list)
    for r in csv_rows:
        fields_by_event[r["event"]].append(r)

    for ev in all_events:
        cfg = classified.get(ev)
        if cfg and cfg.get("exclude"):
            excluded_events.append({"event": ev, "reason": cfg["exclude"]})
            continue
        if cfg is None:
            unclassified_events.append(ev)
            tech, cat, cell_scoped = default_tech, default_category, False
        else:
            tech = cfg.get("tech", "Shared"); cat = cfg.get("category", "Unclassified")
            cell_scoped = bool(cfg.get("cell_scoped", False))
        # Dédoublonnage "Capture context" : toujours tech=Shared (BC3 2.50.3).
        if cat == "Capture context": tech = "Shared"
        if cat not in CATEGORIES and cat != default_category: cat = "Unclassified"
        # category node (lazy create)
        cat_key = (tech, cat)
        if cat_key not in cat_nodes:
            cat_nodes[cat_key] = {"node_type": "category", "tech": tech,
                                  "label": cat, "node_id": f"cat_{tech}_{slugify(cat)}",
                                  "parent_id": f"tech_{tech}"}
        # event node
        ev_nid = f"ev_{slugify(ev)}"
        event_nodes[ev] = {"node_type": "event", "label": ev, "event": ev,
                           "node_id": ev_nid, "parent_id": cat_nodes[cat_key]["node_id"],
                           "cell_scoped": cell_scoped,
                           "tech": tech}
        # leaves : one per field; cell-scoped events get per-cell_type leaves
        kept_fields = []
        for row in fields_by_event[ev]:
            name = row["name"]
            if name in STRUCTURAL_FIELDS or name in IDENTITY_FIELDS or \
               name in MASKED_INDEX_FIELDS or name in PAYLOAD_FIELDS:
                exclude_fields_total += 1
                continue
            kept_fields.append(row)
        if cell_scoped:
            cells_seen = sorted(cell_coverage.get(ev, set()))
            # 2.51.0 — 7 feuilles cellule canoniques (PCell, SCell 1-4, PSCell,
            # SCell NR 100+). Chaque feuille porte `cell_type` filtre dimension ;
            # selectable=false + reason si cell_type jamais observé en base.
            # Dédoublonnage des 32 feuilles spec par event : BC3 2026-10-25.
            SEVEN = [
                (0, "PCell", "PCell (0)", 7),
                (1, "SCell 1", "SCell 1 (1)", 7),
                (2, "SCell 2", "SCell 2 (2)", 7),
                (3, "SCell 3", "SCell 3 (3)", 7),
                (4, "SCell 4", "SCell 4 (4)", 7),
                (199, "PSCell", "PSCell NR (199)", 9),
                (100, "SCell NR 100+", "SCell NR 100+ (bucket cell_type≥100 hors PSCell)", 9),
            ]
            scell_nr_observed = any(c >= 100 and c != 199 for c in cells_seen)
            for ct, label_short, label_long, tech_cell in SEVEN:
                if ct == 100:
                    observed = scell_nr_observed
                else:
                    observed = ct in cells_seen
                # Évince PSCell + SCell NR 100+ pour un event LTE-only
                # (tech=LTE) et SCell 1..4 pour un event NR-only (tech=NR).
                applicable = (
                    tech == "Shared"
                    or (tech == "LTE" and tech_cell == 7)
                    or (tech == "NR" and tech_cell == 9)
                )
                reason = None
                selectable = observed
                if not applicable:
                    selectable = False
                    reason = f"N/A — event {tech}-only (cell_type {ct} n'existe que côté {'NR' if tech_cell==9 else 'LTE'})"
                elif not observed:
                    reason = "cell_type jamais observé en base (BC3 2026-10-25)"
                for row in kept_fields:
                    name = row["name"]
                    # Les champs *_fil et extra_N : FF 2.62 non documenté 2.50.
                    extras_reason = None
                    extras_selectable = selectable
                    if any(suffix in name.lower() for suffix in ("extra_", "_fil")):
                        extras_selectable = False
                        extras_reason = "FF 2.62 non documenté 2.50 — nommage par contenu BC3 2026-10-25"
                    leaves_cell.append({
                        "node_type": "leaf", "event": ev, "label": f"{row['name']} @ {label_short}",
                        "metric_id": f"{ev.lower()}_{slugify(row['name'])}@{ct}",
                        # 2.51.1 — source_column tirée du YAML du décodeur, jamais
                        # inventée depuis le label CSV. Chaîne vide si pas de
                        # mapping YAML (événement hors corpus décodé).
                        "source_column": source_column_for(ev, row["name"]),
                        "cell_type": ct, "cell_label": label_long, "parent_id": ev_nid,
                        "node_id": f"lf_{slugify(ev)}_{slugify(row['name'])}_c{ct}",
                        "field_no": row.get("field_no"), "type": row.get("type"),
                        "unit": row.get("unit") or None, "range": row.get("range") or None,
                        "description": row.get("description") or None,
                        "proof": "documented-2.50",
                        "selectable": bool(extras_selectable), "displayed": True,
                        "reason": extras_reason or reason, "n": 0,
                    })
        else:
            for row in kept_fields:
                leaves_bare.append({
                    "node_type": "leaf", "event": ev, "label": row["name"],
                    "metric_id": f"{ev.lower()}_{slugify(row['name'])}", "parent_id": ev_nid,
                    # 2.51.1 — source_column YAML, pas convention nom.
                    "source_column": source_column_for(ev, row["name"]),
                    "node_id": f"lf_{slugify(ev)}_{slugify(row['name'])}",
                    "field_no": row.get("field_no"), "type": row.get("type"),
                    "unit": row.get("unit") or None, "range": row.get("range") or None,
                    "description": row.get("description") or None,
                    "proof": "documented-2.50", "selectable": True,
                    "displayed": True, "n": 0,
                })

    nodes.extend(cat_nodes.values())
    nodes.extend(event_nodes.values())
    nodes.extend(leaves_bare)
    nodes.extend(leaves_cell)

    n_metrics = len(leaves_bare)
    n_leaves = len(leaves_bare) + len(leaves_cell)
    n_displayed = sum(1 for lf in (leaves_bare + leaves_cell) if lf.get("displayed", True))
    print(f"[build] tech={len(tech_nodes)} categories={len(cat_nodes)} events_kept={len(event_nodes)}")
    print(f"[build] excluded_events={len(excluded_events)} unclassified={len(unclassified_events)}")
    print(f"[build] fields_excluded_total={exclude_fields_total}")
    print(f"[build] n_metrics_bare={n_metrics} leaves_cell={len(leaves_cell)} n_leaves_total={n_leaves}")
    print(f"[build] n_leaves_displayed={n_displayed}  <-- contrat G18b")

    # 2.51.1+ — Build déterministe : AUCUN champ non-reproductible dans
    # le JSON (pas de `generated_at`, pas de chemin absolu `source_*`,
    # pas de données DB). Deux builds consécutifs sur les mêmes entrées
    # (CSV spec + categories.yaml + schemas() YAML) → sha identique.
    # Les métadonnées variables (timestamp, chemin source) vivent dans
    # un fichier annexe `<out>.meta.json` HORS fichier versionné.
    payload = {
        "catalog_version": args.version,
        "spec_version": spec_v,
        "decoder_min_version": args.decoder_min,
        "n_tech": len(tech_nodes),
        "n_categories": len(cat_nodes),
        "n_events_kept": len(event_nodes),
        "n_metrics": n_metrics,  # feuilles hors cellule
        "n_leaves": n_leaves,
        "n_leaves_displayed": n_displayed,
        "excluded_events": excluded_events,
        "unclassified_events": unclassified_events,
        "enums": enums,
        "nodes": nodes,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    # Métadonnées non-reproductibles → fichier annexe .meta.json (sidecar).
    # Non versionné dans l'image, utile pour debug uniquement.
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps({
        "catalog_version": args.version,
        "sha256": sha,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_csv": args.csv,
        "source_txt": args.txt,
    }, sort_keys=True, indent=2))
    print(f"[build] out={out_path} sha256={sha}")
    print(f"[build] meta={meta_path} (sidecar, non versionné)")

    if args.commit:
        db = SessionLocal()
        try:
            db.execute(text("UPDATE catalog_release SET is_current=FALSE WHERE is_current=TRUE"))
            db.execute(text(
                "INSERT INTO catalog_release(version, spec_version, decoder_min_version, "
                "sha256, n_categories, n_metrics, n_leaves, changelog, is_current) "
                "VALUES(:v,:s,:d,:sha,:nc,:nm,:nl,:cl,TRUE) "
                "ON CONFLICT(version) DO UPDATE SET sha256=excluded.sha256, "
                "n_categories=excluded.n_categories, n_metrics=excluded.n_metrics, "
                "n_leaves=excluded.n_leaves, is_current=TRUE"
            ), {"v": args.version, "s": spec_v, "d": args.decoder_min, "sha": sha,
                "nc": len(cat_nodes), "nm": n_metrics, "nl": n_leaves,
                "cl": f"gen from {Path(args.csv).name}; unclassified={len(unclassified_events)}; excluded={len(excluded_events)}"})
            db.commit()
            print(f"[build] catalog_release row v={args.version} is_current=TRUE")
        finally:
            db.close()

if __name__ == "__main__":
    main()
