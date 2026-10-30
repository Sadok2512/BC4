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

Variables :
  --version <X.Y.Z> : nom du fichier catalog_<X.Y.Z>.json (requis)
  --changelog "..." : commentaire (défaut : "bootstrap post-reset")

Le mode par défaut, également explicitable avec `--prepare-only`, valide
l'artefact sans ouvrir de session de base. `--activate` est le seul mode qui
écrit et exige un DEPLOY_LOCK dont `holder: BC3`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.scripts.deploy_guard import guard_bc3_deploy_lock  # noqa: E402
from app.kpi.catalog_release.registry import (  # noqa: E402
    CATALOG_DIR,
    catalog_file_path,
    sha256_file,
)


SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

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


def prepare_analytics_minor(source_version: str, target_version: str) -> Path:
    """Clone a catalog release and add the explicit Analytics tab contract.

    Classification uses structural catalog content: event-derived calculations
    are KPI, message fields are Metrics, and residual ambiguity defaults to
    Metrics. The target must be the next MINOR release; labels are ignored.
    """
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
    payload["catalog_version"] = target_version

    target_path = catalog_file_path(target_version)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"artefact cible existant différent : {target_path}")
    target_path.write_text(rendered, encoding="utf-8")
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
        help="clone cette release vers le MINOR suivant et ajoute analytics_tab",
    )
    ap.add_argument("--changelog", default="bootstrap post-reset")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true",
                      help="valide l'artefact sans ouvrir la base (défaut)")
    mode.add_argument("--activate", action="store_true",
                      help="active la release ; exige un DEPLOY_LOCK holder=BC3")
    args = ap.parse_args(argv)

    if args.from_version:
        try:
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
        db.commit()
        print(f"[bootstrap] catalog_release v={args.version} is_current=TRUE sha256={sha}  "
              f"n_categories={payload['n_categories']} n_metrics={payload['n_metrics']} "
              f"n_leaves={payload['n_leaves']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
