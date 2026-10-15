#!/usr/bin/env python3
"""One-shot : peuple `param_occurrence` pour tous les projets déjà ingérés.

Introduit avec 0.12.0 — à lancer UNE FOIS pour les projets qui ont été
ingérés avant ce lot (p.ex. TEST2 avec 19 380 events). Les nouveaux
uploads peuplent automatiquement via `refresh_project_summary`.

Idempotent : la table est purgée par projet puis re-peuplée. Un
rejeu produit exactement les mêmes lignes.

Lancement (dans le conteneur) :
    docker exec bc4-api-1 python /app/scripts/populate_dict_for_all_projects.py
"""
from __future__ import annotations

import sys

from sqlalchemy import select

try:
    from app.db import SessionLocal
    from app.dict.populate import populate_param_occurrence
    from app.models import Project
except ModuleNotFoundError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.db import SessionLocal
    from app.dict.populate import populate_param_occurrence
    from app.models import Project


def main() -> int:
    total_projects = 0
    total_written = 0
    total_denied = 0

    with SessionLocal() as db:
        # On ne touche que les projets qui ont un ingest (status_ingest NOT NULL).
        projects = (
            db.execute(select(Project).where(Project.status_ingest.is_not(None)))
            .scalars()
            .all()
        )
        for p in projects:
            total_projects += 1
            print(f"[dict] {p.id} ({p.name}) : populate…", flush=True)
            stats = populate_param_occurrence(db, p.id, purge=True)
            total_written += stats["n_params_written"]
            total_denied += stats["n_params_denied"]
            print(
                f"[dict] {p.id} ({p.name}) : "
                f"events_scanned={stats['events_scanned']}, "
                f"ok={stats['events_decoded_ok']}, err={stats['events_decoded_err']}, "
                f"params_written={stats['n_params_written']}, "
                f"params_denied={stats['n_params_denied']}, "
                f"errors={stats['errors']}",
                flush=True,
            )
        print(
            f"[dict] projets scannés = {total_projects}, "
            f"params écrits total = {total_written}, "
            f"params denied total = {total_denied}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
