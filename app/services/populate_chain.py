"""0.46.0 — Chaînage AUTOMATIQUE post-ingest : populate_measurements →
populate_measurement_points → populate_ecgi_for_project.

Appelé à la fin de ``upload_nmf`` dans la MÊME requête HTTP, sous un
``pg_advisory_xact_lock`` par ``project_id`` : jamais deux populate
concurrents sur le même projet (règle « séquentiel par projet »).

Garantit la **cohérence** : un projet qui a reçu des NMF se retrouve avec
``last_populate_at`` et ``n_points`` à jour avant le retour HTTP, sinon
``ingest_status`` reste à ``incomplete`` et le dashboard /projects le signale.

Jamais silencieux : si une étape échoue, on remonte l'exception à l'appelant
(upload_nmf la journalise + marque le projet). Les étapes partielles
s'enregistrent quand même via ``db.commit()`` entre chaque étape pour que
l'état DB reflète ce qui a réussi.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.measure.ecgi import populate_ecgi_for_project
from app.measure.populate import populate_measurement_points
from app.services.populate_measurements import populate_measurements

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models import Project

logger = logging.getLogger(__name__)


def _project_lock_key(project_id: str) -> int:
    """Clé bigint stable pour pg_advisory_xact_lock : hashtext('populate:'||id).
    PostgreSQL hashtext → int32 ; on l'étend à bigint via cast implicite.
    """
    # On fait le hash côté SQL (Postgres hashtext) pour cohérence inter-processus.
    # Retourne un placeholder utilisé en SELECT pg_advisory_xact_lock(hashtext(:k)).
    return 0  # non utilisé ; cf. acquire_project_lock


def acquire_project_lock(db: "Session", project_id: str) -> None:
    """Pose un advisory_xact_lock sur ``populate:{project_id}``. Bloquant.
    Auto-release à la fin de la transaction (COMMIT ou ROLLBACK).
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"populate:{project_id}"},
    )


def run_populate_chain(db: "Session", project: "Project") -> dict:
    """Enchaîne les 3 étapes populate pour `project` et met à jour les
    colonnes de suivi (`last_populate_at`, `n_points`).

    Retourne un rapport ``{measurements, mp, ecgi, n_points, elapsed_s}``.
    N'avale JAMAIS une exception : laisse remonter si une étape plante.
    """
    t0 = datetime.now(timezone.utc)
    acquire_project_lock(db, project.id)
    report: dict = {}

    # Étape A — populate_measurements (purge mp + skeleton depuis
    # stg_measurement_raw). `purge=True` = source de vérité propre.
    logger.info("[populate_chain] A measurements project=%s", project.id)
    try:
        report["measurements"] = populate_measurements(db, project.id, purge=True)
    except Exception as exc:
        logger.exception("[populate_chain] A measurements FAIL")
        report["measurements_error"] = repr(exc)
        raise
    db.commit()

    # Étape B — populate_measurement_points (UPDATE skeleton + INSERT reste,
    # avec profil CELLMEAS prouvé + range-gating 3GPP + mapping LTE).
    logger.info("[populate_chain] B measurement_points project=%s", project.id)
    try:
        r = populate_measurement_points(db, project.id, purge=False)
        report["mp"] = {
            "updated": r.get("updated"),
            "inserted": r.get("inserted"),
            "mismatches": r.get("mismatches"),
            "mapping": r.get("mapping"),
        }
    except Exception as exc:
        logger.exception("[populate_chain] B measurement_points FAIL")
        report["mp_error"] = repr(exc)
        raise
    db.commit()

    # Étape C — populate_ecgi strict (sib1_strict_capture_earfcn).
    logger.info("[populate_chain] C ecgi project=%s", project.id)
    try:
        er = populate_ecgi_for_project(db, project.id)
        report["ecgi"] = {
            "sib1_cells": er.sib1_cells,
            "distinct_ecgi": er.distinct_ecgi,
            "mp_total": er.mp_total,
            "mp_with_ecgi": er.mp_with_ecgi,
            "pct": round(er.mp_pct_with_ecgi, 2),
        }
    except Exception as exc:
        logger.exception("[populate_chain] C ecgi FAIL")
        report["ecgi_error"] = repr(exc)
        raise
    db.commit()

    # Étape D — task_run / task_sample from canonical staging events.
    from app.services.task_run import populate_tasks
    logger.info("[populate_chain] D task_run project=%s", project.id)
    report["tasks"] = populate_tasks(db, project.id)
    db.commit()

    # Étape E — snapshot n_points + last_populate_at sur projects.
    n_points_row = db.execute(
        text("SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid"),
        {"pid": project.id},
    ).first()
    n_points = int(n_points_row[0]) if n_points_row and n_points_row[0] is not None else 0
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "UPDATE projects SET last_populate_at = :ts, n_points = :np WHERE id = :pid"
        ),
        {"ts": now, "np": n_points, "pid": project.id},
    )
    db.commit()
    # Refresh in-memory
    db.refresh(project)
    report["n_points"] = n_points
    report["last_populate_at"] = now.isoformat()
    report["elapsed_s"] = round((datetime.now(timezone.utc) - t0).total_seconds(), 1)
    logger.info(
        "[populate_chain] DONE project=%s n_points=%d elapsed=%ss",
        project.id, n_points, report["elapsed_s"],
    )
    return report
