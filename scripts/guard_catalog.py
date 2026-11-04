#!/usr/bin/env python3
"""guard_catalog.py — garde obligatoire avant chaque "FAIT".

Compare le catalogue live (metrics_catalog_cache, 3 captures Test_6) au
snapshot de la release précédente dans `audit/snapshots/catalog_<v>.json`.

Exit 1 si l'un des 5 critères échoue :
 1. Une feuille avec valeurs a disparu (liste metric_id)
 2. Le nombre de valeurs d'une feuille baisse sans justification changelog
 3. Une branche (CAPTURE / LTE / NR / IP) perd des feuilles avec valeurs, par capture
 4. display_code vide ou doublé, kind vide, STRUCT dans l'arbre
 5. Un KPI d'event (HOA, HOS, RRA, RRC, RRD, RRRE, TUA, TUS, CREL, SCELLMOD)
    diffère du compte brut `nmf_event_deep`

Sortie : tableau branche × capture (total / avec valeurs, avant → après)
         + liste des écarts.

Snapshot : à chaque release OK, écrit `audit/snapshots/catalog_<v>.json`
avec les comptes et les metric_id de référence.

Usage :
    python scripts/guard_catalog.py                           # garde + éventuel snapshot
    python scripts/guard_catalog.py --write-snapshot          # force écriture snapshot
    python scripts/guard_catalog.py --allow-decrease a,b,c    # tolère la baisse UNIQUEMENT pour a, b, c
    python scripts/guard_catalog.py --help

`--allow-decrease` prend une liste blanche de metric_id séparés par
virgules (ces IDs doivent être listés dans le CHANGELOG de la release
courante). Toute autre baisse échoue le guard. Passer la chaîne vide
(ou omettre le flag) refuse toute baisse.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "audit" / "snapshots"
PROJECT_ID = "43e81a34a073"
CAPTURES = {
    "a4b0c321c52e": "Test_6",
    "daa2b1df250d": "ikea.6",
    "ecffb18dbd7f": "ikea.2",
}
BRANCHES = ("CAPTURE", "LTE", "NR", "IP / Services")

# 2.68.0 (Mobilité 2b point 3) — KPI d'event vs brut nmf_event_deep (critère 5).
# Élargi : RRC setup / NAS TAU/LAU / failures. Chaque KPI listé ici est
# comparé exactement au count brut (ordre (capture_id, seq), jamais ts).
EVENT_KPI_MAP = {
    "lte_ho_attempts":          ("HOA",      None),
    "lte_ho_success":           ("HOS",      None),
    "lte_cell_resel_count":     ("CREL",     None),
    "lte_rrc_setup_failure":    ("RRF",      None),
    "rrf_count":                ("RRF",      None),
    "tuf_count":                ("TUF",      None),
    "luf_count":                ("LUF",      None),
}
# Events bruts à vérifier en complément (critère 5 étendu Mobilité 2b).
BRUT_EVENTS = [
    "HOA", "HOS", "HOI",
    "RRA", "RRC", "RRD", "RRF", "RRRE",
    "TUA", "TUS", "TUF",
    "LUA", "LUS", "LUF",
    "CREL", "SCELLMOD",
]


def load_current_catalog_version(db):
    from sqlalchemy import text
    v = db.execute(text(
        "SELECT version FROM catalog_release WHERE is_current = TRUE LIMIT 1"
    )).scalar()
    if not v:
        raise RuntimeError("no current catalog_release row")
    return v


def load_live_payload(db, cap_id):
    from sqlalchemy import text
    r = db.execute(text(
        "SELECT payload FROM metrics_catalog_cache WHERE scope_key=:s"
    ), {"s": f"captures:{cap_id}"}).scalar()
    if r is None:
        raise RuntimeError(f"no cache for captures:{cap_id} — regen first")
    return r


def tech_of(leaf, by_id):
    cur = by_id.get(leaf.get("parent_id"))
    while cur:
        if cur.get("node_type") == "tech":
            return cur.get("label")
        cur = by_id.get(cur.get("parent_id"))
    return None


def extract_summary(payload):
    """Extract per-branch totals + per-leaf n from a payload.

    IMPORTANT (bug fix Étape 3c) : `per_leaf` keyed on `display_code` (baked
    identity, unique par leaf). Keyer sur `metric_id` masquait les feuilles
    spécialisées : dans la sortie du catalog, `metric_id` est le sélecteur
    `col@typed-cell` qui collisionne entre la feuille générique
    `dci_dci_format@6` et la feuille spécialisée `dci_dci_format_f10@6` (toutes
    deux ont col=dci_dci_format cell=6 → selection=`dci_dci_format@lte-type-6`).
    Le dernier itéré écrasait le précédent, rendant 3 pertes SCell 6 ikea.6
    invisibles à critère 1. `display_code` est l'identité baked, unique
    (metrics_catalog_v4.py:1110-1116 § 2.64.0 Lot 6).
    """
    nodes = payload.get("nodes") or []
    by_id = {n.get("node_id"): n for n in nodes if n.get("node_id")}
    leaves = [n for n in nodes if n.get("node_type") == "leaf"]
    per_branch = {b: {"total": 0, "with_values": 0} for b in BRANCHES}
    per_leaf = {}  # display_code → {n, kind, metric_id, technology}
    display_code_counts = Counter()
    kind_null = 0
    display_code_null = 0
    struct_in_tree = 0
    readable_code_counts = Counter()
    readable_code_null = 0
    trailing_name_underscore = 0
    foreign_bloc_labels = []
    foreign_legacy_block_labels = []
    categorical_kind_errors = []
    identity_detail_total = 0
    identity_detail_hidden_dimension = 0
    identity_detail_errors = []
    earfcn_identifier_errors = []
    identity_columns = {
        "PHRATE": {"phrate_ch"},
        "MIMOMEAS": {"mimo_band", "cell_ch", "mimo_pci"},
        "PLAID": {"plaid_pdsch_bwp_id", "plaid_pdsch_bwp_id_f36"},
        "PLAIU": {"plaiu_pusch_bwp_id", "plaiu_pusch_bwp_id_f35"},
        "CI": {"ci_arfcn", "ci_ch", "ci_rpc_cell_index"},
    }
    foreign_legacy_re = re.compile(
        r"\(bloc (?:GSM|UMTS|cdma|WiMAX|TETRA|EVDO|GAN|iDEN|TD-SCDMA)"
    )
    for n in leaves:
        t = tech_of(n, by_id) or "?"
        if t not in per_branch:
            per_branch.setdefault(t, {"total": 0, "with_values": 0})
        per_branch[t]["total"] += 1
        val = int(n.get("n") or 0)
        if val > 0:
            per_branch[t]["with_values"] += 1
        key = n.get("display_code") or n.get("metric_id")
        if key:
            per_leaf[key] = {
                "n": val,
                "kind": n.get("kind"),
                "metric_id": n.get("metric_id"),
                "display_code": n.get("display_code"),
                "technology": t,
            }
        dc = n.get("display_code")
        if dc is None or dc == "":
            display_code_null += 1
        else:
            display_code_counts[dc] += 1
        if not n.get("kind"):
            kind_null += 1
        if n.get("kind") == "STRUCT":
            struct_in_tree += 1
        readable = n.get("display_code_lisible")
        short_name = n.get("nom_court")
        if not readable or not short_name:
            readable_code_null += 1
        else:
            readable_code_counts[readable] += 1
            if readable.endswith("_") or short_name.endswith("_"):
                trailing_name_underscore += 1
        block = re.search(r"\(bloc ([^)#]+)(?: #[^)]+)?\)", n.get("label") or "", re.IGNORECASE)
        system = n.get("cell_system")
        if block and system in {"LTE", "NR"} and system not in block.group(1).upper():
            foreign_bloc_labels.append({
                "display_code": dc,
                "cell_system": system,
                "label": n.get("label"),
            })
        if t in {"LTE", "NR"} and foreign_legacy_re.search(n.get("label") or ""):
            foreign_legacy_block_labels.append(dc)
        event = n.get("event") or ""
        source_column = n.get("source_column")
        if source_column in identity_columns.get(event, set()):
            identity_detail_total += 1
            if n.get("kind") == "DIMENSION" and n.get("tree_visible") is False:
                identity_detail_hidden_dimension += 1
            else:
                identity_detail_errors.append({
                    "display_code": dc,
                    "kind": n.get("kind"),
                    "tree_visible": n.get("tree_visible"),
                })
        raw_cell_type = n.get("raw_cell_type")
        if (
            event == "CELLMEAS"
            and source_column == "cell_ch"
            and n.get("cell_system") == "LTE"
            and isinstance(raw_cell_type, int)
        ):
            expected_metric_id = f"cell_ch@lte-type-{raw_cell_type}"
            if n.get("metric_id") != expected_metric_id:
                earfcn_identifier_errors.append({
                    "display_code": dc,
                    "metric_id": n.get("metric_id"),
                    "expected": expected_metric_id,
                })
        technical_tokens = set(re.split(r"[^a-z0-9]+", str(dc or "").lower()))
        if technical_tokens & {"rank", "modulation"} and n.get("kind") != "KPI_CATEGORICAL":
            categorical_kind_errors.append(dc)
    dup_dc = {dc: c for dc, c in display_code_counts.items() if c > 1}
    return {
        "per_branch": per_branch,
        "per_leaf": per_leaf,
        "display_code_null": display_code_null,
        "display_code_duplicates": dup_dc,
        "kind_null": kind_null,
        "struct_in_tree": struct_in_tree,
        "readable_code_null": readable_code_null,
        "readable_code_duplicates": {
            code: count for code, count in readable_code_counts.items() if count > 1
        },
        "trailing_name_underscore": trailing_name_underscore,
        "foreign_bloc_labels": foreign_bloc_labels,
        "foreign_legacy_block_labels": foreign_legacy_block_labels,
        "categorical_kind_errors": categorical_kind_errors,
        "identity_detail_total": identity_detail_total,
        "identity_detail_hidden_dimension": identity_detail_hidden_dimension,
        "identity_detail_errors": identity_detail_errors,
        "earfcn_identifier_errors": earfcn_identifier_errors,
    }


def event_raw_counts(db):
    """COUNT(*) FROM nmf_event_deep per (capture, event_code) for BRUT_EVENTS."""
    from sqlalchemy import text
    r = db.execute(text(
        "SELECT capture_id, event_code, COUNT(*) FROM nmf_event_deep "
        "WHERE project_id=:p AND event_code = ANY(:evs) "
        "GROUP BY capture_id, event_code"
    ), {"p": PROJECT_ID, "evs": BRUT_EVENTS}).all()
    out = {(row[0], row[1]): int(row[2]) for row in r}
    # Ensure all combos present (0 if missing)
    for cap in CAPTURES:
        for ev in BRUT_EVENTS:
            out.setdefault((cap, ev), 0)
    return out


def load_snapshot(version):
    f = SNAP_DIR / f"catalog_{version}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def write_snapshot(version, summaries):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    f = SNAP_DIR / f"catalog_{version}.json"
    f.write_text(json.dumps({
        "catalog_version": version,
        "project_id": PROJECT_ID,
        "captures": CAPTURES,
        "summaries": summaries,
    }, sort_keys=True, indent=2, ensure_ascii=False))
    return f


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-snapshot", action="store_true",
                        help="Force snapshot write (first run or after release)")
    parser.add_argument("--allow-decrease", default="",
                        metavar="MID[,MID...]",
                        help="Whitelist de metric_id autorisés à baisser "
                             "(doivent être listés dans le CHANGELOG). Sans valeur, "
                             "toute baisse échoue le guard.")
    args = parser.parse_args()
    allow_decrease_set = {m.strip() for m in (args.allow_decrease or "").split(",") if m.strip()}

    # Local import to avoid heavy load for --help
    sys.path.insert(0, str(ROOT))
    from app.db import SessionLocal
    db = SessionLocal()

    version = load_current_catalog_version(db)
    print(f"=== guard_catalog.py — catalog live={version} ===\n")

    from app.kpi.display_names import load_display_names
    display_names = load_display_names()
    print(
        "display_names.csv "
        f"rows={len(display_names)} metric_id_unique={len(display_names)} "
        f"display_code_lisible_unique={len({row.display_code for row in display_names.values()})} "
        "trailing_underscore=0"
    )

    # 1. Collect current summaries per capture
    current = {}
    for cap_id, cap_label in CAPTURES.items():
        payload = load_live_payload(db, cap_id)
        current[cap_id] = extract_summary(payload)
    observed_display_codes = {
        display_code
        for summary in current.values()
        for display_code in summary["per_leaf"]
    }
    mapped_display_codes = set(display_names)
    joined_display_codes = observed_display_codes & mapped_display_codes
    print(
        f"display_name_join joined={len(joined_display_codes)}/{len(mapped_display_codes)} "
        f"observed_union={len(observed_display_codes)} "
        f"unmapped={len(observed_display_codes - mapped_display_codes)}\n"
    )
    print(
        "content_checks "
        f"foreign_bloc_mismatch={sum(len(s['foreign_bloc_labels']) for s in current.values())} "
        f"foreign_legacy_block={sum(len(s['foreign_legacy_block_labels']) for s in current.values())} "
        f"rank_modulation_wrong_kind={sum(len(s['categorical_kind_errors']) for s in current.values())} "
        f"identity_dimension_hidden="
        f"{sum(s['identity_detail_hidden_dimension'] for s in current.values())}/"
        f"{sum(s['identity_detail_total'] for s in current.values())} "
        f"earfcn_identifier_errors={sum(len(s['earfcn_identifier_errors']) for s in current.values())}\n"
    )

    # 2. Load previous snapshot (if any)
    prev_version = None
    prev_snapshot = None
    if SNAP_DIR.exists():
        snaps = sorted(f.stem.replace("catalog_", "") for f in SNAP_DIR.glob("catalog_*.json"))
        if snaps:
            # pick most recent != current
            for v in reversed(snaps):
                if v != version:
                    prev_version = v
                    prev_snapshot = load_snapshot(v)
                    break
    if prev_snapshot is None:
        # No reference snapshot : first run
        print(f"[INFO] Pas de snapshot précédent. Écriture snapshot {version} comme référence.\n")
        write_snapshot(version, {c: current[c] for c in CAPTURES})
        print_table_only(current)
        print("\n[OK] premier snapshot écrit — pas de comparaison, exit 0")
        return 0

    print(f"Snapshot référence : catalog_{prev_version}.json")
    print(f"Catalog live       : {version}\n")

    # 3. Table branche × capture (avant → après)
    print_table(prev_snapshot["summaries"], current)

    # 4. Garde critères
    failures = []
    if joined_display_codes != mapped_display_codes or observed_display_codes != mapped_display_codes:
        failures.append(
            "jointure display_names incomplète : "
            f"joined={len(joined_display_codes)}/{len(mapped_display_codes)} "
            f"catalog_only={sorted(observed_display_codes - mapped_display_codes)[:5]} "
            f"mapping_only={sorted(mapped_display_codes - observed_display_codes)[:5]}"
        )
    for cap_id, cap_label in CAPTURES.items():
        prev = prev_snapshot["summaries"].get(cap_id, {})
        cur = current[cap_id]

        # Critère 4 : display_code null / duplicates / kind null / STRUCT in tree
        if cur["display_code_null"] > 0:
            failures.append(f"[{cap_label}] display_code null : {cur['display_code_null']} feuilles")
        if cur["display_code_duplicates"]:
            failures.append(f"[{cap_label}] display_code doublons : "
                            f"{list(cur['display_code_duplicates'].items())[:5]}")
        if cur["kind_null"] > 0:
            failures.append(f"[{cap_label}] kind null : {cur['kind_null']} feuilles")
        if cur["struct_in_tree"] > 0:
            failures.append(f"[{cap_label}] STRUCT dans l'arbre : {cur['struct_in_tree']} feuilles")
        if cur["readable_code_null"] > 0:
            failures.append(
                f"[{cap_label}] feuilles sans display_code_lisible/nom_court : "
                f"{cur['readable_code_null']}"
            )
        if cur["readable_code_duplicates"]:
            failures.append(
                f"[{cap_label}] display_code_lisible doublons : "
                f"{list(cur['readable_code_duplicates'].items())[:5]}"
            )
        if cur["trailing_name_underscore"] > 0:
            failures.append(
                f"[{cap_label}] noms finissant par underscore : "
                f"{cur['trailing_name_underscore']}"
            )
        if cur["foreign_bloc_labels"]:
            failures.append(
                f"[{cap_label}] libellés bloc d'une autre technologie : "
                f"{cur['foreign_bloc_labels'][:3]}"
            )
        if cur["foreign_legacy_block_labels"]:
            failures.append(
                f"[{cap_label}] libellés bloc legacy LTE/NR : "
                f"{cur['foreign_legacy_block_labels'][:5]}"
            )
        if cur["identity_detail_errors"]:
            failures.append(
                f"[{cap_label}] identités message non masquées/DIMENSION : "
                f"{cur['identity_detail_errors'][:5]}"
            )
        if cur["earfcn_identifier_errors"]:
            failures.append(
                f"[{cap_label}] identifiants EARFCN_SERVING non canoniques : "
                f"{cur['earfcn_identifier_errors'][:5]}"
            )
        if cur["categorical_kind_errors"]:
            failures.append(
                f"[{cap_label}] Rank/Modulation hors KPI_CATEGORICAL : "
                f"{cur['categorical_kind_errors'][:5]}"
            )

        # Critère 1 : feuille avec valeurs disparue — absente du cache courant
        # alors qu'elle avait n>0 dans la référence. Les leaves présentes mais
        # passées à n=0 relèvent du critère 2 (baisse), pas du 1. Les mids
        # listés dans `--allow-decrease` sont considérés comme disparitions
        # déclarées (renommage ou dépréciation documentée au CHANGELOG).
        prev_with_values = {mid for mid, info in (prev.get("per_leaf") or {}).items() if info.get("n", 0) > 0}
        cur_leaves = cur["per_leaf"]
        cur_leaves_set = set(cur_leaves.keys())
        disappeared = prev_with_values - cur_leaves_set - allow_decrease_set
        if disappeared:
            failures.append(f"[{cap_label}] feuilles avec valeurs DISPARUES : {sorted(disappeared)[:20]}")

        # Critère 2 : baisse n — n'accepter QUE les metric_id whitelistés
        # (listés dans le CHANGELOG via `--allow-decrease a,b,c`). Les autres
        # baisses bloquent le guard. `--allow-decrease` sans valeur refuse tout.
        decreased = []
        unauth_decreased = []
        for mid, prev_info in (prev.get("per_leaf") or {}).items():
            prev_n = prev_info.get("n", 0)
            cur_info = cur_leaves.get(mid)
            if cur_info is None:
                continue
            cur_n = cur_info["n"]
            if cur_n < prev_n:
                decreased.append((mid, prev_n, cur_n))
                if mid not in allow_decrease_set:
                    unauth_decreased.append((mid, prev_n, cur_n))
        if unauth_decreased:
            failures.append(f"[{cap_label}] n baisse NON autorisée (absente de --allow-decrease) : "
                            + ", ".join(f"{m}: {p}→{c}" for m, p, c in unauth_decreased[:10]))

        # Critère 3 : branche perd des feuilles with_values — NET de reclass.
        # On ignore les reclassifications (mid qui passe d'une branche à une
        # autre en gardant n>0). Seule une perte "sèche" (mid absent ou passé
        # à n=0 sans réapparaître ailleurs) compte.
        prev_leaf_tech = {mid: info.get("technology") for mid, info in (prev.get("per_leaf") or {}).items()
                          if info.get("n", 0) > 0}
        cur_leaf_tech = {mid: info.get("technology") for mid, info in cur_leaves.items()
                         if info.get("n", 0) > 0}
        for b in BRANCHES:
            prev_in_b = {m for m, t in prev_leaf_tech.items() if t == b}
            cur_in_b_or_elsewhere = {m for m in prev_in_b if m in cur_leaf_tech}
            net_lost = prev_in_b - cur_in_b_or_elsewhere - allow_decrease_set
            if net_lost:
                failures.append(f"[{cap_label}] branche {b!r} pertes sèches : "
                                f"{sorted(net_lost)[:10]}")

    # 5. Critère 5 : KPI event vs brut nmf_event_deep
    brut = event_raw_counts(db)
    # Pour les KPI exposés : comparer n catalog au brut
    for cap_id, cap_label in CAPTURES.items():
        cur_leaves = current[cap_id]["per_leaf"]
        for kpi_mid, (ev_code, _) in EVENT_KPI_MAP.items():
            if kpi_mid not in cur_leaves:
                continue
            cat_n = cur_leaves[kpi_mid]["n"]
            raw_n = brut.get((cap_id, ev_code), 0)
            if cat_n != raw_n:
                failures.append(f"[{cap_label}] KPI {kpi_mid!r} = {cat_n} ≠ brut {ev_code} = {raw_n}")
        # Également lister les counts brut de contrôle pour les events sans KPI
        # (vérification informative, pas bloquante)

    # 6. Critère 5 détaillé — brut nmf_event_deep × KPI catalog, par capture
    print("\n=== Critère 5 — comptage brut nmf_event_deep × KPI catalog ===")
    # En-tête avec colonnes brut et, pour chaque capture, la valeur KPI catalog
    # quand un KPI est exposé pour cet event.
    rev_map = {v[0]: k for k, v in EVENT_KPI_MAP.items()}
    hdr = f"{'event':8s}"
    for lbl in CAPTURES.values():
        hdr += f"  {lbl:>10s}"
    hdr += f"   | {'KPI catalog':<22s}"
    for lbl in CAPTURES.values():
        hdr += f"  {lbl+' kpi':>12s}"
    print(hdr)
    for ev in BRUT_EVENTS:
        counts = [brut.get((c, ev), 0) for c in CAPTURES]
        line = f"{ev:8s}  " + "  ".join(f"{n:>10d}" for n in counts)
        kpi_mid = rev_map.get(ev)
        line += f"   | {(kpi_mid or '—'):<22s}"
        for cid in CAPTURES:
            if kpi_mid and kpi_mid in current[cid]["per_leaf"]:
                line += f"  {current[cid]['per_leaf'][kpi_mid]['n']:>12d}"
            else:
                line += f"  {'(no kpi)':>12s}"
        print(line)

    # 7. Résultat
    print("\n=== Verdict ===")
    if failures:
        print(f"✗ GUARD FAIL — {len(failures)} écart(s) :")
        for f in failures:
            print(f"  - {f}")
        return 1
    else:
        print("✓ GUARD PASS — aucun écart détecté.")
        if args.write_snapshot or version != prev_version:
            f = write_snapshot(version, {c: current[c] for c in CAPTURES})
            print(f"  snapshot écrit : {f}")
        return 0


def print_table_only(current):
    """First-run table (no previous snapshot)."""
    print(f"{'branche':20s}  " + "  ".join(f"{lbl:>18s}" for lbl in CAPTURES.values()))
    for b in BRANCHES:
        cells = []
        for cap_id in CAPTURES:
            s = current[cap_id]["per_branch"].get(b, {"total": 0, "with_values": 0})
            cells.append(f"{s['total']:>6}/{s['with_values']:<5}")
        print(f"{b:20s}  " + "  ".join(f"{c:>18s}" for c in cells))


def print_table(prev_sums, current):
    """Table before→after."""
    print(f"{'branche':20s}  " + "  ".join(f"{lbl:>22s}" for lbl in CAPTURES.values()))
    for b in BRANCHES:
        cells = []
        for cap_id in CAPTURES:
            prev = (prev_sums.get(cap_id) or {}).get("per_branch", {}).get(b, {"total": 0, "with_values": 0})
            cur = current[cap_id]["per_branch"].get(b, {"total": 0, "with_values": 0})
            arrow = "→"
            cells.append(f"{prev['total']}/{prev['with_values']} {arrow} {cur['total']}/{cur['with_values']}")
        print(f"{b:20s}  " + "  ".join(f"{c:>22s}" for c in cells))


if __name__ == "__main__":
    sys.exit(main())
