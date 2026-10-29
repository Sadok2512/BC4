"""0.46.0 — Chaînage AUTOMATIQUE post-ingest : populate_measurements →
populate_measurement_points → populate_ecgi_for_project.

Appelé à la fin de ``upload_nmf`` dans la MÊME requête HTTP, sous un
``pg_advisory_lock`` de session par ``project_id`` : jamais deux populate
concurrents sur le même projet, même si chaque tranche est commitée.

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

def _run_populate_chain(db: "Session", project: "Project") -> dict:
    """Enchaîne les 3 étapes populate pour `project` et met à jour les
    colonnes de suivi (`last_populate_at`, `n_points`).

    Retourne un rapport ``{measurements, mp, ecgi, n_points, elapsed_s}``.
    N'avale JAMAIS une exception : laisse remonter si une étape plante.
    """
    t0 = datetime.now(timezone.utc)
    report: dict = {}

    from app.nmf_decoder.store import ensure_light
    report["decoder"] = ensure_light(db, project.id)

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
    from app.measure.cellmeas_repair import assert_lte_enriched
    assert_lte_enriched(db, project.id)
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

    # Étape E — métriques Nemo dont les positions sont prouvées.
    from app.services.metric_samples import populate_metric_samples
    report["metrics"] = populate_metric_samples(db, project.id)
    db.commit()

    # Étape F — projection Signaling immuable par génération. Les écritures
    # sont commit-tées par tranches et l'activation n'arrive qu'à la fin.
    from app.signaling.materialized import materialize_project
    logger.info("[populate_chain] F signaling project=%s", project.id)
    report["signaling"] = materialize_project(db, project.id)

    # Étape G — snapshot n_points + last_populate_at sur projects.
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


def run_populate_chain(db, project):
    """Exécute la finalisation avec de vrais commits bornés et reprise sûre.

    Le verrou advisory est attaché à la connexion, pas à une transaction : il
    sérialise un projet pendant que les commits de tranches libèrent réellement
    MVCC. Un arrêt peut laisser un préfixe valide ; la relance idempotente
    converge sans doublon.
    """
    from sqlalchemy.orm import Session
    from app.models import Project
    from app.db import engine
    # Reading an expired ORM attribute starts a transaction in the caller.
    # Capture the identity and finish that short metadata transaction BEFORE
    # the independent, potentially long population transaction. Never touch
    # the expired caller object again until the population commit completes.
    project_id = project.id
    db.commit()
    lock_key = 'populate:' + project_id
    with engine.connect() as connection:
        with Session(bind=connection, expire_on_commit=False) as work:
            work.execute(text('SELECT pg_advisory_lock(hashtext(:k))'), {'k': lock_key})
            work.commit()
            try:
                stored = work.get(Project, project_id)
                if stored is None:
                    raise LookupError(f'project_not_found:{project_id}')
                report = _run_populate_chain(work, stored)
            finally:
                work.rollback()
                work.execute(
                    text('SELECT pg_advisory_unlock(hashtext(:k))'),
                    {'k': lock_key},
                )
                work.commit()
    db.refresh(project)
    return report
