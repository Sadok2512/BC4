"""Catalog release registry — accès lecture seule depuis les routes.

Une seule ligne is_current=TRUE à la fois (contrainte en base, migration 0047).
`/metrics` et `/metrics/table` lisent cette ligne pour exposer la version du
catalogue + decoder_min_version.

Aucun chiffre inventé : si `catalog_release` est vide (bootstrap frais), la
fonction retourne None et le route conserve l'ancien comportement — jamais
de default silencieux.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

CATALOG_DIR = Path(__file__).parent


@dataclass(frozen=True)
class CurrentCatalog:
    version: str
    spec_version: str
    decoder_min_version: str
    sha256: str
    n_leaves: int


def current_catalog(db: Session) -> CurrentCatalog | None:
    row = db.execute(
        text(
            "SELECT version, spec_version, decoder_min_version, sha256, n_leaves "
            "FROM catalog_release WHERE is_current = TRUE LIMIT 1"
        )
    ).first()
    if not row:
        return None
    return CurrentCatalog(
        version=row[0],
        spec_version=row[1],
        decoder_min_version=row[2],
        sha256=row[3],
        n_leaves=int(row[4]),
    )


def load_catalog_json(version: str) -> dict:
    """Charge `catalog_<version>.json` depuis le dossier. Jamais de default."""
    path = CATALOG_DIR / f"catalog_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"Catalog artefact absent on disk: {path}")
    with path.open("rb") as f:
        return json.load(f)


def sha256_file(path: os.PathLike | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
