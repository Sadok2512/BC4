#!/usr/bin/env python3
"""One-shot : miroiter B1-ingest -> B0 pour les projets déjà ingérés.

Introduit avec 0.11.1 — à lancer UNE FOIS pour aligner les projets qui
ont été ingérés avant ce patch (p.ex. TEST2 live avec 9 fichiers NMF).
Les nouveaux uploads miroitent automatiquement via
`refresh_project_summary`.

Portée stricte :
  - captures     <- n_captures_ingest, si non None.
  - technologies <- clés de technos_seen triées par -count, si non-vide.
  - operators    : NON TOUCHÉ (operators_plmn={} tant que PLMN pas câblé).
  - geography /
    departements : NON TOUCHÉS (reverse-geocoding hors scope).

Pas de migration de schéma, pas d'Alembic — c'est de la donnée.
Idempotent : rejouer le script ne change rien de plus qu'un refresh.

Lancement (dans le conteneur) :
    docker exec bc4-api-1 python /app/scripts/mirror_ingest_to_b0.py
"""

from __future__ import annotations

import sys
from typing import Any

from sqlalchemy import select

# Le script peut être lancé via `python scripts/mirror_ingest_to_b0.py`
# depuis la racine du dépôt OU `python /app/scripts/mirror_ingest_to_b0.py`
# dans le conteneur — dans les deux cas, `app` doit être importable.
try:
    from app.db import SessionLocal
    from app.models import Project
except ModuleNotFoundError:
    # Fallback : ajouter la racine du dépôt (parent de scripts/) au sys.path.
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.db import SessionLocal
    from app.models import Project


def mirror_one(project: Project) -> dict[str, Any]:
    """Applique le miroitage à un projet. Retourne un diff lisible.
    Pas d'écrasement d'operators / geography / departements.
    """
    changes: dict[str, Any] = {}

    if project.n_captures_ingest is not None and project.captures != project.n_captures_ingest:
        changes["captures"] = (project.captures, project.n_captures_ingest)
        project.captures = project.n_captures_ingest

    if isinstance(project.technos_seen, dict) and project.technos_seen:
        # Filtre identique à `refresh_project_summary` : vocabulaire Zod
        # `{LTE, NR, EN-DC}`. technos_seen peut contenir des clés hors-Zod
        # (p.ex. "UMTS") — elles restent visibles sur l'ingest view mais
        # ne polluent pas `project.technologies` (sinon pydantic rejette).
        zod_techs = {"LTE", "NR", "EN-DC"}
        new_techs = [
            k for k in sorted(
                project.technos_seen.keys(),
                key=lambda k: -int(project.technos_seen[k]),
            )
            if k in zod_techs
        ]
        if (project.technologies or []) != new_techs:
            changes["technologies"] = (project.technologies, new_techs)
            project.technologies = new_techs

    return changes


def main() -> int:
    touched = 0
    seen = 0
    with SessionLocal() as db:
        # On ne touche que les projets qui ont un ingest (status_ingest NOT NULL).
        # Les projets seedés B0 (status_ingest IS NULL) sont LAISSÉS intacts.
        projects = (
            db.execute(select(Project).where(Project.status_ingest.is_not(None)))
            .scalars()
            .all()
        )
        for p in projects:
            seen += 1
            diff = mirror_one(p)
            if diff:
                touched += 1
                print(f"[mirror] {p.id} ({p.name}): {diff}")
        if touched:
            db.commit()
        print(f"[mirror] projets ingérés scannés = {seen}, modifiés = {touched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
