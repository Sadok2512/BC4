"""Bootstrap `catalog_release` depuis un JSON `app/kpi/catalog_release/catalog_<v>.json`.

Scénario : base vide (post `DROP DATABASE bc4` + `alembic upgrade head`).
`alembic/versions/0048_catalog_release.py` crée la table mais ne pose
aucune ligne. Ce script lit un JSON catalog déjà sur disque et calcule son
sha256 avec `app.kpi.catalog_release.registry.sha256_file`. Par défaut il
s'arrête là ; `--activate`, sous verrou BC3, pose la ligne
`catalog_release` courante via l'engine SQLAlchemy du dépôt.

Usage (idempotent, upsert sur `version`) :
  python scripts/catalog/bootstrap_catalog_release.py --version 2.53.0
  python scripts/catalog/bootstrap_catalog_release.py --version 2.53.0 --activate

Préparer une release mineure qui ajoute le classement KPI Analytics sans
activer la base (la bascule reste une commande séparée et explicite) :
  python scripts/catalog/bootstrap_catalog_release.py --version 2.57.0 \
    --from-version 2.56.2 --prepare-only

Préparer les libellés LTE/NR de la release catalogue suivante :
  python scripts/catalog/bootstrap_catalog_release.py --to 2.58.0 \
    --from 2.57.0 --transform nr-labels --prepare-only

Préparer la visibilité des séries désormais prises en charge :
  python scripts/catalog/bootstrap_catalog_release.py --to 2.59.0 \
    --from 2.58.0 --transform visible-leaves --prepare-only

Variables :
  --version <X.Y.Z> : nom du fichier catalog_<X.Y.Z>.json (requis)
  --changelog "..." : commentaire (défaut : "bootstrap post-reset")

Le mode par défaut, également explicitable avec `--prepare-only`, valide
l'artefact sans ouvrir de session de base. `--activate` est le seul mode qui
écrit et exige un DEPLOY_LOCK dont `holder: BC3`.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.scripts.deploy_guard import guard_bc3_deploy_lock  # noqa: E402
from app.scripts.invalidate_catalog_cache import (  # noqa: E402
    invalidate_catalog_cache,
    write_audit as write_cache_invalidation_audit,
)
from app.kpi.catalog_release.registry import (  # noqa: E402
    CATALOG_DIR,
    catalog_file_path,
    sha256_file,
)


SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
CATALOG_SYSTEM_LABELS = {7: "LTE", 9: "NR"}

# Décisions issues du replay exhaustif Test_6 avec max_points=2000. Elles sont
# écrites dans l'artefact 2.57.0 : le serveur construit l'arbre depuis ce champ,
# le front ne contient donc aucune liste d'exclusion.
ANALYTICS_SERIES_REMOVALS: tuple[tuple[str, str, str], ...] = (
    ("cell_ch@lte-type-2", "CELLMEAS", "categorical_transitions_exceed_max_points:required=5449:max_points=2000"),
    ("cell_pci@lte-type-2", "CELLMEAS", "categorical_transitions_exceed_max_points:required=19957:max_points=2000"),
    ("cell_pci@nr-type-1000", "CELLMEAS", "categorical_transitions_exceed_max_points:required=9540:max_points=2000"),
    *((code, event, "unknown_metric") for event, codes in {
        "CQI": [f"cqi_n_params@lte-type-{cell}" for cell in range(5)],
        "CREL": ["crel_band", "crel_cell_id", "crel_new_tac", "crel_old_band", "crel_old_cell_id", "crel_old_system", "crel_old_tac", "crel_params"],
        "DAD": ["dad_application_protocol", "dad_data_disc_status"],
        "DCOMP": ["dcomp_application_protocol", "dcomp_transf_status"],
        "DREQ": ["dreq_application_protocol", "dreq_transf_dir"],
        "GAD": ["gad_detach_cause", "gad_detach_status", "gad_detach_time"],
        "HOA": ["hoa_att_band", "hoa_att_ch", "hoa_att_pci", "hoa_band", "hoa_ch_number", "hoa_current_system", "hoa_hoa_type", "hoa_pci"],
        "HOI": ["hoi_ho_duration", "hoi_ho_u_plane"],
        "LOCK": ["lock_band", "lock_forcings", "lock_params"],
        "MEI": ["mei_measurement_event", "mei_measurement_id"],
        "PBA": ["pba_pb_type"],
        "PBC": ["pbc_pb_id"],
        "RACHI": ["rachi_access_delay", "rachi_init_tx_power", "rachi_pathloss", "rachi_preamble_step", "rachi_preambles", "rachi_pusch_power", "rachi_rach_preamble_index", "rachi_rach_reason", "rachi_rach_result", "rachi_rach_type"],
        "ROAM": ["roam_roaming_status"],
        "RRA": ["rra_est_cause"],
        "RRD": ["rrd_rrc_rel_cause", "rrd_rrc_rel_status"],
        "SEI": ["sei_mcc", "sei_mme_code", "sei_mme_group", "sei_mnc", "sei_service_status"],
    }.items() for code in codes),
)


def analytics_classification(leaf: dict) -> tuple[str, str]:
    """Classify from catalog content only; labels are deliberately ignored."""
    if leaf.get("analytics_computation") == "event_derived":
        return "kpi", "computed_from_events"
    if leaf.get("event"):
        return "metrics", "message_measurement"
    return "metrics", "ambiguous_defaults_to_metrics"


def _validate_next_minor(source_version: str, target_version: str) -> None:
    source_match = SEMVER_RE.fullmatch(source_version)
    target_match = SEMVER_RE.fullmatch(target_version)
    if not source_match or not target_match:
        raise ValueError("versions attendues au format X.Y.Z")
    source_semver = tuple(map(int, source_match.groups()))
    target_semver = tuple(map(int, target_match.groups()))
    if target_semver != (source_semver[0], source_semver[1] + 1, 0):
        raise ValueError(
            f"la cible doit être le MINOR suivant : "
            f"{source_semver[0]}.{source_semver[1] + 1}.0"
        )


def _write_catalog_artifact(payload: dict, target_version: str) -> Path:
    payload["catalog_version"] = target_version
    target_path = catalog_file_path(target_version)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"artefact cible existant différent : {target_path}")
    target_path.write_text(rendered, encoding="utf-8")
    return target_path


def _cell_leaf_system(leaf: dict) -> int:
    """Infer LTE/NR from structural catalog content, never from the label."""
    field_system = leaf.get("field_system")
    if field_system in CATALOG_SYSTEM_LABELS:
        return int(field_system)
    event = leaf.get("event")
    cell_type = leaf.get("cell_type")
    if not isinstance(cell_type, int):
        raise ValueError(f"feuille sans cell_type : {leaf.get('node_id')}")
    if event == "CELLMEAS":
        return 7 if cell_type in range(5) else 9
    if event == "MIMOMEAS":
        return 7 if cell_type == 0 or cell_type in range(10, 14) else 9
    raise ValueError(f"event non pris en charge : {event}")


def _system_label(label: str, system: int) -> str:
    """Replace the legacy block suffix with an explicit LTE/NR label."""
    if " @ " in label:
        field_label, cell_label = label.split(" @ ", 1)
        cell_suffix = f" @ {cell_label}"
    else:
        field_label = label
        cell_suffix = ""
    field_label = re.sub(r" \(bloc (?:LTE|NR)(?: #[^)]+)?\)$", "", field_label)
    return f"{field_label} ({CATALOG_SYSTEM_LABELS[system]}){cell_suffix}"


def prepare_nr_labels_minor(source_version: str, target_version: str) -> Path:
    """Clone a catalog and make CELLMEAS/MIMOMEAS labels system-explicit.

    ``event``, ``field_system`` and ``cell_type`` decide the system. Labels are
    output only and never participate in the decision. This function writes the
    deterministic JSON artifact and never opens a database session.
    """
    _validate_next_minor(source_version, target_version)
    source_path = catalog_file_path(source_version)
    if not source_path.exists():
        raise FileNotFoundError(f"catalogue source absent : {source_path}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    leaves = [node for node in payload.get("nodes", []) if node.get("node_type") == "leaf"]
    if not leaves:
        raise ValueError("catalogue source sans feuille")

    relabeled = 0
    by_system = {7: 0, 9: 0}
    for leaf in leaves:
        if leaf.get("event") not in {"CELLMEAS", "MIMOMEAS"}:
            continue
        system = _cell_leaf_system(leaf)
        leaf["label_system"] = system
        leaf["label"] = _system_label(leaf["label"], system)
        by_system[system] += 1
        relabeled += 1

    duplicate_labels: dict[tuple[str | None, str], list[str]] = {}
    for leaf in leaves:
        key = (leaf.get("parent_id"), leaf["label"])
        duplicate_labels.setdefault(key, []).append(leaf["node_id"])
    duplicates = {key: ids for key, ids in duplicate_labels.items() if len(ids) > 1}
    if duplicates:
        sample = next(iter(duplicates.items()))
        raise ValueError(f"libellés dupliqués après transformation : {sample}")

    payload["catalog_label_policy"] = {
        "events": ["CELLMEAS", "MIMOMEAS"],
        "source": "NFF 2.50 event + field_system/cell_type + param",
        "system_field": "field_system",
        "inferred_label_system_field": "label_system",
        "systems": {"7": "LTE", "9": "NR"},
        "label_fields_used_for_classification": False,
        "duplicate_scope": "parent_id + label",
    }
    target_path = _write_catalog_artifact(payload, target_version)
    print(
        f"[bootstrap] prepared NR labels v={target_version} from={source_version} "
        f"relabeled={relabeled} lte={by_system[7]} nr={by_system[9]} "
        f"duplicate_labels=0 sha256={sha256_file(target_path)}"
    )
    return target_path


def prepare_visible_leaves_minor(source_version: str, target_version: str) -> Path:
    """Unmask only the 61 series supported by metrics back ``12ff6f0``.

    The source decisions remain the authority: this transform never derives a
    code from a label and refuses a source whose exact decision set diverges
    from the catalog 2.57/2.58 contract. It only writes the JSON artifact.
    """
    _validate_next_minor(source_version, target_version)
    source_path = catalog_file_path(source_version)
    if not source_path.exists():
        raise FileNotFoundError(f"catalogue source absent : {source_path}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    decisions = payload.get("analytics_series_decisions", [])
    expected = {(code, event) for code, event, _reason in ANALYTICS_SERIES_REMOVALS}
    removable = {
        (row.get("code"), row.get("event"))
        for row in decisions
        if row.get("decision") == "removed_until_series_supported"
        and row.get("visible") is False
    }
    if removable != expected:
        missing = sorted(expected - removable)
        unexpected = sorted(removable - expected)
        raise ValueError(
            "décisions de séries inattendues : "
            f"missing={missing[:3]} unexpected={unexpected[:3]}"
        )

    changed = 0
    for row in decisions:
        if (row.get("code"), row.get("event")) not in expected:
            continue
        row["previous_decision"] = row["decision"]
        row["previous_reason"] = row["reason"]
        row["visible"] = True
        row["decision"] = "visible_series_supported"
        row["reason"] = "supported_by_metrics_series_12ff6f0"
        row["support_commit"] = "12ff6f0"
        changed += 1

    payload["analytics_visibility_policy"] = {
        "source_field": "analytics_series_decisions",
        "selection": "decision=removed_until_series_supported and visible=false",
        "support_commit": "12ff6f0",
        "label_fields_used": False,
        "unmasked": changed,
    }
    target_path = _write_catalog_artifact(payload, target_version)
    print(
        f"[bootstrap] prepared visible leaves v={target_version} "
        f"from={source_version} unmasked={changed} "
        f"sha256={sha256_file(target_path)}"
    )
    return target_path


def _clone_scell_leaf(template: dict, scell_index: int) -> dict:
    """Clone one SCell 4 leaf from structural cell metadata."""
    clone = copy.deepcopy(template)
    event = clone.get("event")
    template_type = int(clone["cell_type"])
    lte_offset_type = event == "CELLMEAS" or (
        event == "MIMOMEAS"
        and (template.get("label_system") == 7 or template_type == 13)
    )
    target_type = scell_index + 9 if lte_offset_type else scell_index

    source_identity = 13 if event == "MIMOMEAS" and template_type == 13 else 4
    target_identity = target_type if source_identity == 13 else scell_index
    node_suffix = f"_c{source_identity}"
    metric_suffix = f"@{source_identity}"
    if not clone["node_id"].endswith(node_suffix):
        raise ValueError(f"identité SCell 4 inattendue : {clone['node_id']}")
    if not clone["metric_id"].endswith(metric_suffix):
        raise ValueError(f"metric_id SCell 4 inattendu : {clone['metric_id']}")
    clone["node_id"] = clone["node_id"][:-len(node_suffix)] + f"_c{target_identity}"
    clone["metric_id"] = clone["metric_id"][:-len(metric_suffix)] + f"@{target_identity}"
    clone["cell_type"] = target_type
    clone["label"] = clone["label"].replace("SCell 4", f"SCell {scell_index}")
    if event == "CELLMEAS":
        clone["cell_label"] = f"SCell {scell_index} (raw {target_type})"
    else:
        clone["cell_label"] = f"SCell {scell_index} ({target_type})"

    # Explicit system metadata stays authoritative.  The remaining common
    # SCell 0..31 families in the 2.59 catalog are LTE decoder schemas.
    if clone.get("field_system") is None:
        clone["field_system"] = int(clone.get("label_system") or 7)
    return clone


def prepare_scell5plus_minor(source_version: str, target_version: str) -> Path:
    """Clone the complete SCell 4 families to SCell 5 and SCell 6.

    This deterministic preparation writes only the catalog artifact on disk.
    """
    _validate_next_minor(source_version, target_version)
    source_path = catalog_file_path(source_version)
    if not source_path.exists():
        raise FileNotFoundError(f"catalogue source absent : {source_path}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    leaves = [node for node in nodes if node.get("node_type") == "leaf"]
    templates = [
        leaf for leaf in leaves
        if leaf.get("cell_type") == 4
        or (leaf.get("event") == "MIMOMEAS" and leaf.get("cell_type") == 13)
    ]
    if not templates:
        raise ValueError("catalogue source sans famille SCell 4")

    existing_ids = {node["node_id"] for node in nodes}
    additions = []
    by_scell = {5: 0, 6: 0}
    for scell_index in (5, 6):
        for template in templates:
            clone = _clone_scell_leaf(template, scell_index)
            if clone["node_id"] in existing_ids:
                raise ValueError(f"feuille cible déjà présente : {clone['node_id']}")
            existing_ids.add(clone["node_id"])
            additions.append(clone)
            by_scell[scell_index] += 1

    payload["nodes"] = nodes + additions
    payload["n_leaves"] = sum(
        node.get("node_type") == "leaf" for node in payload["nodes"]
    )
    payload["n_leaves_displayed"] = sum(
        node.get("node_type") == "leaf" and bool(node.get("displayed"))
        for node in payload["nodes"]
    )
    payload["catalog_scell_policy"] = {
        "source_family": "SCell 4",
        "added_scell_indices": [5, 6],
        "cellmeas_lte_raw_types": {"5": 14, "6": 15},
        "mimomeas_lte_raw_types": {"5": 14, "6": 15},
        "other_lte_raw_types": {"5": 5, "6": 6},
        "label_fields_used_for_selection": False,
        "added_leaves": len(additions),
    }
    target_path = _write_catalog_artifact(payload, target_version)
    print(
        f"[bootstrap] prepared SCell 5+ v={target_version} from={source_version} "
        f"scell5={by_scell[5]} scell6={by_scell[6]} "
        f"added={len(additions)} sha256={sha256_file(target_path)}"
    )
    return target_path


def prepare_analytics_minor(source_version: str, target_version: str) -> Path:
    """Clone a catalog release and add the explicit Analytics tab contract.

    Classification uses structural catalog content: event-derived calculations
    are KPI, message fields are Metrics, and residual ambiguity defaults to
    Metrics. The target must be the next MINOR release; labels are ignored.
    """
    _validate_next_minor(source_version, target_version)

    source_path = catalog_file_path(source_version)
    if not source_path.exists():
        raise FileNotFoundError(f"catalogue source absent : {source_path}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    leaves = [node for node in payload.get("nodes", []) if node.get("node_type") == "leaf"]
    if not leaves:
        raise ValueError("catalogue source sans feuille")
    residual_ambiguous = []
    for leaf in leaves:
        tab, reason = analytics_classification(leaf)
        leaf["analytics_tab"] = tab
        leaf["analytics_classification"] = reason
        if reason == "ambiguous_defaults_to_metrics":
            residual_ambiguous.append(leaf["node_id"])
    payload["analytics_classification_policy"] = {
        "kpi": "analytics_computation=event_derived",
        "computed_from_events_tab": "kpi",
        "metrics": "event identifies a field read from a message",
        "message_measurement_tab": "metrics",
        "fallback": "metrics",
        "label_fields_used": False,
        "residual_ambiguous_node_ids": sorted(residual_ambiguous),
    }
    payload["analytics_series_decisions"] = [
        {
            "code": code,
            "event": event,
            "visible": False,
            "decision": "removed_until_series_supported",
            "reason": reason,
        }
        for code, event, reason in ANALYTICS_SERIES_REMOVALS
    ]
    target_path = _write_catalog_artifact(payload, target_version)
    print(
        f"[bootstrap] prepared catalog v={target_version} from={source_version} "
        f"kpi={sum(leaf['analytics_tab'] == 'kpi' for leaf in leaves)} "
        f"metrics={sum(leaf['analytics_tab'] == 'metrics' for leaf in leaves)} "
        f"residual_ambiguous={len(residual_ambiguous)} "
        f"series_removed={len(ANALYTICS_SERIES_REMOVALS)} "
        f"sha256={sha256_file(target_path)}"
    )
    return target_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", "--to", dest="version", required=True, help="ex. 2.53.0")
    ap.add_argument(
        "--from-version", "--from", dest="from_version",
        help="clone cette release vers le MINOR suivant",
    )
    ap.add_argument(
        "--transform",
        choices=("analytics", "nr-labels", "visible-leaves", "scell5plus"),
        default="analytics",
        help="transformation disque appliquée avec --from (défaut : analytics)",
    )
    ap.add_argument("--changelog", default="bootstrap post-reset")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true",
                      help="valide l'artefact sans ouvrir la base (défaut)")
    mode.add_argument("--activate", action="store_true",
                      help="active la release ; exige un DEPLOY_LOCK holder=BC1 ou BC4")
    args = ap.parse_args(argv)

    if args.from_version:
        try:
            if args.transform == "nr-labels":
                prepare_nr_labels_minor(args.from_version, args.version)
            elif args.transform == "visible-leaves":
                prepare_visible_leaves_minor(args.from_version, args.version)
            elif args.transform == "scell5plus":
                prepare_scell5plus_minor(args.from_version, args.version)
            else:
                prepare_analytics_minor(args.from_version, args.version)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[bootstrap] FAIL — {exc}", file=sys.stderr)
            return 2
    path = catalog_file_path(args.version)
    if not path.exists():
        print(f"[bootstrap] FAIL — fichier absent : {path}", file=sys.stderr)
        return 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    sha = sha256_file(path)
    missing = [k for k in ("spec_version", "decoder_min_version", "n_categories", "n_metrics", "n_leaves") if k not in payload]
    if missing:
        print(f"[bootstrap] FAIL — métadonnées manquantes dans JSON : {missing}", file=sys.stderr)
        return 2

    if not args.activate:
        print(f"[bootstrap] prepared-only catalog_release v={args.version} sha256={sha} "
              f"n_categories={payload['n_categories']} n_metrics={payload['n_metrics']} "
              f"n_leaves={payload['n_leaves']} database_write=FALSE")
        return 0

    if not guard_bc3_deploy_lock(action="catalog_release.activate"):
        return 1

    db = SessionLocal()
    try:
        db.execute(text("UPDATE catalog_release SET is_current=FALSE WHERE is_current=TRUE"))
        db.execute(text(
            "INSERT INTO catalog_release(version, spec_version, decoder_min_version, "
            "sha256, n_categories, n_metrics, n_leaves, changelog, is_current) "
            "VALUES(:v,:s,:d,:sha,:nc,:nm,:nl,:cl,TRUE) "
            "ON CONFLICT(version) DO UPDATE SET spec_version=excluded.spec_version, "
            "decoder_min_version=excluded.decoder_min_version, sha256=excluded.sha256, "
            "n_categories=excluded.n_categories, n_metrics=excluded.n_metrics, "
            "n_leaves=excluded.n_leaves, changelog=excluded.changelog, is_current=TRUE"
        ), {
            "v": args.version,
            "s": payload["spec_version"],
            "d": payload["decoder_min_version"],
            "sha": sha,
            "nc": payload["n_categories"],
            "nm": payload["n_metrics"],
            "nl": payload["n_leaves"],
            "cl": args.changelog,
        })
        cache_report = invalidate_catalog_cache(
            db,
            reason=f"catalog activation {args.version}: {args.changelog}",
            source="bootstrap_catalog_release --activate",
        )
        db.commit()
        cache_audit = write_cache_invalidation_audit(cache_report)
        print(f"[bootstrap] catalog_release v={args.version} is_current=TRUE sha256={sha}  "
              f"n_categories={payload['n_categories']} n_metrics={payload['n_metrics']} "
              f"n_leaves={payload['n_leaves']}")
        print(
            f"[bootstrap] catalog_cache rows_before={cache_report['rows_before']} "
            f"rows_deleted={cache_report['rows_deleted']} "
            f"rows_rebuilt={cache_report['rows_rebuilt']} "
            f"rows_after={cache_report['rows_after']} audit={cache_audit}"
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
