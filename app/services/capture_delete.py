"""Suppression applicative, projet-scopée, d'une capture NMF.

La clé d'identité est toujours ``(project_id, capture_id)``.  Un même
``capture_id`` peut exister dans plusieurs projets ; aucune suppression ni
aucun DROP de partition ne peut donc être décidé sur ``capture_id`` seul.
"""
from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import text

from app.db import engine
from app.ingest.nmf import refresh_project_summary
from app.models import Project
from app.services.import_jobs import active_job, update_capture_counts
from app.services.import_worker import LOCK_ID
from app.services.populate_chain import run_populate_chain


MIN_REASON_LENGTH = 10
_CAPTURE_ID = re.compile(r"^[a-f0-9]{12,64}$")

# Tables possédant directement les deux colonnes de scope. L'ordre est celui
# des dépendances : enfants d'abord, staging et snapshot en dernier.
CAPTURE_TABLES = (
    "signaling_materialized_event",
    "signaling_materialized_point",
    "signaling_materialized_capture",
    "task_run",
    "superstream_member",
    "signaling_procedure",
    "rrc_observations",
    "measurement_points",
    "metric_sample",
    "range_violations",
    "nmf_event_pair",
    "nmf_event_light_group",
    "nmf_event_light_ext",
    "nmf_event_light_native",
    "nmf_event_light",
    "nmf_event_group",
    "nmf_event_deep",
    "nmf_cell_second",
)

# Vues ou tables à comptage indirect. ``nmf_metric_value`` est une vue issue
# de nmf_event_deep/light ; ``param_occurrence`` référence stg_event.
COUNT_ONLY_TABLES = ("nmf_metric_value", "param_occurrence")
STAGING_TABLES = ("stg_event", "stg_event_raw", "stg_measurement_raw")
ALL_CAPTURE_DATA = CAPTURE_TABLES + COUNT_ONLY_TABLES + STAGING_TABLES + ("nmf_capture",)


class CaptureDeleteError(RuntimeError):
    """Base des refus métier de suppression."""


class CaptureNotFound(CaptureDeleteError):
    pass


class CaptureDeleteBusy(CaptureDeleteError):
    pass


class CaptureDeleteIntegrityError(CaptureDeleteError):
    pass


class CaptureDeleteFinalizationError(CaptureDeleteError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _audit_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / "audit" / "capture_delete"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_audit(report: dict[str, Any]) -> Path:
    stamp = report["started_at"].replace("-", "").replace(":", "").split(".")[0]
    capture_id = report["capture_id"]
    target = _audit_dir() / f"{stamp}_{capture_id}_{report['op_id'][:8]}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def _count(db, table: str, project_id: str, capture_id: str) -> int:
    params = {"pid": project_id, "cap": capture_id}
    if table == "param_occurrence":
        sql = """SELECT count(*) FROM param_occurrence p
                 JOIN stg_event e ON e.id=p.stg_event_id
                 WHERE p.project_id=:pid AND e.project_id=:pid AND e.capture_id=:cap"""
    else:
        # Les noms viennent exclusivement des constantes internes ci-dessus.
        sql = f"SELECT count(*) FROM {table} WHERE project_id=:pid AND capture_id=:cap"
    return int(db.execute(text(sql), params).scalar_one())


def capture_counts(db, project_id: str, capture_id: str) -> dict[str, int]:
    return {table: _count(db, table, project_id, capture_id) for table in ALL_CAPTURE_DATA}


@contextmanager
def _worker_lock() -> Iterator[None]:
    """Empêche un worker d'import de démarrer pendant toute l'opération."""
    with engine.connect() as lock:
        acquired = bool(
            lock.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}).scalar()
        )
        lock.commit()
        if not acquired:
            raise CaptureDeleteBusy("import_worker_active")
        try:
            yield
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            lock.commit()


def _drop_empty_partitions(db, capture_id: str) -> list[str]:
    """Droppe les partitions uniquement si la capture n'existe nulle part.

    Les partitions sont LIST(capture_id), donc potentiellement partagées par
    plusieurs projets. Le double garde ``nmf_capture`` + parents interdit de
    supprimer les lignes d'un autre projet, même en cas de données partielles.
    """
    if db.get_bind().dialect.name != "postgresql" or not _CAPTURE_ID.fullmatch(capture_id):
        return []
    remaining_snapshots = int(
        db.execute(
            text("SELECT count(*) FROM nmf_capture WHERE capture_id=:cap"),
            {"cap": capture_id},
        ).scalar_one()
    )
    remaining_rows = int(
        db.execute(
            text("""SELECT
                    (SELECT count(*) FROM nmf_event_deep WHERE capture_id=:cap) +
                    (SELECT count(*) FROM nmf_event_group WHERE capture_id=:cap)"""),
            {"cap": capture_id},
        ).scalar_one()
    )
    if remaining_snapshots or remaining_rows:
        return []

    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('nmf_decoder_partition_ddl'))"))
    dropped: list[str] = []
    for prefix in ("nmf_deep_", "nmf_group_"):
        name = prefix + capture_id
        exists = db.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}
        ).scalar_one()
        if exists:
            # capture_id a été validé par la même grammaire que la fonction
            # nmf_decoder_partition ; le nom ne peut contenir aucun métacaractère.
            db.execute(text(f'DROP TABLE "{name}"'))
            dropped.append(name)
    return dropped


def _update_or_delete_file(db, file_id: str) -> tuple[bool, str | None]:
    remaining = int(
        db.execute(
            text("SELECT count(*) FROM nmf_capture WHERE nmf_file_id=:fid"),
            {"fid": file_id},
        ).scalar_one()
    )
    if remaining:
        db.execute(
            text("""UPDATE nmf_file SET
                    n_captures=(SELECT count(*) FROM nmf_capture WHERE nmf_file_id=:fid),
                    n_events=(SELECT count(*) FROM stg_event WHERE nmf_file_id=:fid),
                    n_gps=(SELECT count(*) FROM stg_event_raw
                           WHERE nmf_file_id=:fid
                             AND (lower(category)='gps' OR upper(event_code)='GPS'))
                    WHERE id=:fid"""),
            {"fid": file_id},
        )
        return False, None

    source_path = db.execute(
        text("SELECT source_path FROM nmf_file WHERE id=:fid FOR UPDATE"), {"fid": file_id}
    ).scalar_one_or_none()
    db.execute(text("DELETE FROM nmf_file WHERE id=:fid"), {"fid": file_id})
    return True, source_path


def _unlink_unreferenced_source(source_path: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": source_path, "removed": False, "reason": None}
    if not source_path:
        result["reason"] = "no_source_path"
        return result
    with engine.connect() as connection:
        references = int(
            connection.execute(
                text("SELECT count(*) FROM nmf_file WHERE source_path=:path"),
                {"path": source_path},
            ).scalar_one()
        )
    if references:
        result["reason"] = "still_referenced"
        return result
    path = Path(source_path)
    try:
        path.unlink(missing_ok=True)
        result["removed"] = True
    except OSError as exc:
        result["reason"] = f"unlink_failed:{exc!r}"
    return result


def _recalculate_project(db, project: Project) -> dict[str, Any]:
    """Recalcule les résumés puis les agrégats depuis les captures restantes."""
    # Evite que refresh_project_summary conserve une ancienne valeur lorsque
    # la capture supprimée était la seule à porter un opérateur/une techno.
    project.operators = []
    project.technologies = []
    project.bands = []
    project.operators_plmn = {}
    project.technos_seen = {}
    project.perimeter = None
    update_capture_counts(db, project)
    refresh_project_summary(db, project, populate=False)
    population = run_populate_chain(db, project)
    db.refresh(project)
    return {
        "population": population,
        "n_captures_ingest": project.n_captures_ingest,
        "n_events_ingest": project.n_events_ingest,
        "status_ingest": project.status_ingest,
        "period_start": project.period_start,
        "period_end": project.period_end,
        "operators": project.operators,
    }


def delete_capture(db, project_id: str, capture_id: str, *, reason: str) -> dict[str, Any]:
    """Supprime une capture et finalise le projet, sous verrou worker global."""
    reason = reason.strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ValueError(f"reason_too_short:min={MIN_REASON_LENGTH}")

    report: dict[str, Any] = {
        "op_id": uuid.uuid4().hex,
        "started_at": _utc_now().isoformat(),
        "project_id": project_id,
        "capture_id": capture_id,
        "reason": reason,
        "status": "started",
    }

    with _worker_lock():
        project = (
            db.query(Project).filter(Project.id == project_id).with_for_update().one_or_none()
        )
        if project is None:
            raise CaptureNotFound("project_or_capture_not_found")
        if active_job(db, project_id) is not None:
            raise CaptureDeleteBusy("project_import_active")

        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": "populate:" + project_id},
        )
        params = {"pid": project_id, "cap": capture_id}
        snapshot = db.execute(
            text("""SELECT * FROM nmf_capture
                    WHERE project_id=:pid AND capture_id=:cap FOR UPDATE"""),
            params,
        ).mappings().first()
        if snapshot is None:
            db.rollback()
            raise CaptureNotFound("project_or_capture_not_found")

        snapshot = dict(snapshot)
        file_id = str(snapshot["nmf_file_id"])
        report["before"] = {"snapshot": snapshot, "counts": capture_counts(db, project_id, capture_id)}

        try:
            for table in CAPTURE_TABLES:
                db.execute(
                    text(f"DELETE FROM {table} WHERE project_id=:pid AND capture_id=:cap"),
                    params,
                )
            # Suppression explicite pour audit ; la FK CASCADE de stg_event
            # constitue une deuxième barrière pour param_occurrence.
            db.execute(
                text("""DELETE FROM param_occurrence p USING stg_event e
                        WHERE p.stg_event_id=e.id AND p.project_id=:pid
                          AND e.project_id=:pid AND e.capture_id=:cap"""),
                params,
            )
            for table in STAGING_TABLES:
                db.execute(
                    text(f"DELETE FROM {table} WHERE project_id=:pid AND capture_id=:cap"),
                    params,
                )
            db.execute(
                text("DELETE FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap"),
                params,
            )

            file_deleted, source_path = _update_or_delete_file(db, file_id)
            dropped = _drop_empty_partitions(db, capture_id)
            after_counts = capture_counts(db, project_id, capture_id)
            residual = {table: count for table, count in after_counts.items() if count != 0}
            if residual:
                raise CaptureDeleteIntegrityError(f"residual_rows:{residual}")

            report["after"] = {
                "counts": after_counts,
                "nmf_file_deleted": file_deleted,
                "partitions_dropped": dropped,
            }
            db.commit()
            report["status"] = "delete_committed"
        except Exception:
            db.rollback()
            report["status"] = "rolled_back"
            report["finished_at"] = _utc_now().isoformat()
            report["audit_path"] = str(_write_audit(report))
            raise

        report["source_file"] = (
            _unlink_unreferenced_source(source_path) if file_deleted else
            {"path": None, "removed": False, "reason": "nmf_file_still_referenced"}
        )
        try:
            report["project_after"] = _recalculate_project(db, project)
            report["status"] = "complete"
        except Exception as exc:
            db.rollback()
            report["status"] = "delete_committed_finalization_failed"
            report["finalization_error"] = repr(exc)
            report["finished_at"] = _utc_now().isoformat()
            report["audit_path"] = str(_write_audit(report))
            raise CaptureDeleteFinalizationError(str(report["audit_path"])) from exc

    report["finished_at"] = _utc_now().isoformat()
    audit_path = _write_audit(report)
    report["audit_path"] = str(audit_path)
    # Le chemin est ajouté au retour ; le fichier contient déjà toute la
    # preuve avant/après et n'a pas besoin de s'auto-référencer.
    return report
