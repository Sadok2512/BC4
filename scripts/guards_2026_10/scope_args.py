"""Périmètre commun des gardes catalogue.

Priorité : arguments CLI, puis variables d'environnement, puis projet nommé
`Test_6` (`43e81a34a073`). Sans capture explicite, les captures du projet
sont prises par contenu ; le défaut Test_6 exige exactement trois témoins.
"""
from __future__ import annotations

import argparse
import os
from sqlalchemy import text

DEFAULT_PROJECT_ID = "43e81a34a073"


def add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", "--pid", dest="project_id")
    parser.add_argument(
        "--capture-id", "--cap", dest="capture_ids", action="append",
        help="capture_id (répétable ou liste séparée par des virgules)",
    )


def _split(values: list[str] | None) -> list[str]:
    return [part.strip() for value in (values or [])
            for part in value.split(",") if part.strip()]


def resolve_scope(db, args: argparse.Namespace) -> tuple[str, list[str]]:
    project_id = (
        args.project_id or os.getenv("BC4_PROJECT_ID") or os.getenv("PROJECT_ID")
    )
    default_project = project_id is None
    if default_project:
        project = db.execute(text(
            "SELECT id FROM projects WHERE id=:pid AND name=:name"
        ), {"pid": DEFAULT_PROJECT_ID, "name": "Test_6"}).scalar_one_or_none()
        if project is None:
            raise ValueError(
                f"projet par défaut Test_6 introuvable: id={DEFAULT_PROJECT_ID}"
            )
        project_id = project
    elif db.execute(text(
        "SELECT 1 FROM projects WHERE id=:pid"
    ), {"pid": project_id}).scalar() is None:
        raise ValueError(f"project_id inaccessible: {project_id}")

    env_caps = (
        os.getenv("BC4_CAPTURE_IDS") or os.getenv("CAPTURE_IDS")
        or os.getenv("BC4_CAPTURE_ID") or os.getenv("CAPTURE_ID")
    )
    capture_ids = _split(args.capture_ids or ([env_caps] if env_caps else []))
    available = db.execute(text("""
        SELECT capture_id FROM nmf_capture
        WHERE project_id=:pid ORDER BY capture_id
    """), {"pid": project_id}).scalars().all()
    if capture_ids:
        missing = sorted(set(capture_ids) - set(available))
        if missing:
            raise ValueError(
                f"capture_id hors projet {project_id}: {missing}"
            )
        capture_ids = list(dict.fromkeys(capture_ids))
    else:
        capture_ids = list(available)
        if default_project and len(capture_ids) != 3:
            raise ValueError(
                f"défaut Test_6 exige 3 captures, trouvé={len(capture_ids)}"
            )
    if not capture_ids:
        raise ValueError(f"aucune capture témoin pour project_id={project_id}")
    return project_id, capture_ids
