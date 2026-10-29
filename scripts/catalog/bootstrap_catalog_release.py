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


def prepare_analytics_minor(source_version: str, target_version: str) -> Path:
    """Clone a catalog release and add the explicit Analytics tab contract.

    Catalog 2.56.2 exposes only raw NFF measurement leaves, so every leaf is
    classified as ``metrics``.  The target must be the next MINOR release;
    labels, event names and units are deliberately ignored.
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
    for leaf in leaves:
        leaf["analytics_tab"] = "metrics"
    payload["catalog_version"] = target_version

    target_path = catalog_file_path(target_version)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"artefact cible existant différent : {target_path}")
    target_path.write_text(rendered, encoding="utf-8")
    print(
        f"[bootstrap] prepared catalog v={target_version} from={source_version} "
        f"analytics_tab=metrics leaves={len(leaves)} sha256={sha256_file(target_path)}"
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
