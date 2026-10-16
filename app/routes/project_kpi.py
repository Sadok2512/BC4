"""Endpoints KPI scopés projet — catalogue v2 (0.40.0).

Trois routes publiques (auth lecteur mini, injectée par le router) :
  - GET /projects/{project_id}/kpi/catalog     (+ ?service_type[])
  - GET /projects/{project_id}/kpi/filters
  - GET /projects/{project_id}/kpi/{code}      (+ query filtres)

Scope ``project_id`` injecté SERVEUR via le path (jamais depuis le body).
Zéro ligne brute, zéro SQL exposé — tout agrégé. Jamais de valeur
inventée : si une source est indisponible, le statut est renseigné
(UNVALIDATED | PENDING | UNAVAILABLE | NOT_APPLICABLE) et ``value``
reste ``null``.

0.40.0 — Les routes consomment désormais ``catalog_v2`` (194 KPI
canoniques + 14 alias, soit 208 entrées xlsx) et exposent le filtre
``service_type[]`` pour déclarer ``NOT_APPLICABLE`` sur un KPI hors
scope de service (pas un ``n=0`` muet).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, get_current_user, require_role
from app.kpi.service_v2 import (
    build_catalog_v2_response,
    build_filters_v2,
    compute_kpi_v2,
)
from app.measure.ecgi import populate_ecgi_for_project
from app.models import Project
from app.schemas.settings import Actor


router = APIRouter(
    prefix="/projects",
    tags=["kpi-project"],
    dependencies=[Depends(get_current_user)],
)


def _require_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(
            404, {"code": "NOT_FOUND", "message": "Projet introuvable"}
        )
    return p


@router.get("/{project_id}/kpi/catalog")
def kpi_catalog(
    project_id: str,
    service_type: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    """Catalogue v2 : 194 canoniques + 14 alias (208 input xlsx).

    Si ``service_type[]`` est fourni, les KPI hors scope sont marqués
    ``NOT_APPLICABLE`` dans l'arbre (jamais filtrés silencieusement).
    """
    _require_project(db, project_id)
    return build_catalog_v2_response(
        db, project_id, services=tuple(service_type),
    )


@router.get("/{project_id}/kpi/filters")
def kpi_filters(project_id: str, db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    return build_filters_v2(db, project_id)


@router.post("/{project_id}/kpi/_populate_ecgi")
def kpi_populate_ecgi(
    project_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — déclenche la propagation ECGI pour ce projet.

    Lit SIB1 depuis ``param_occurrence``, construit la liste des
    cellules observées, propage ``measurement_points.ecgi`` par
    ``(capture_id, earfcn)`` et alimente ``cell_ref`` depuis les logs.
    """
    require_role(actor, "admin")
    _require_project(db, project_id)
    report = populate_ecgi_for_project(db, project_id)
    return {
        "project_id":            report.project_id,
        "sib1_cells":            report.sib1_cells,
        "distinct_ecgi":         report.distinct_ecgi,
        "mp_total":              report.mp_total,
        "mp_with_ecgi":          report.mp_with_ecgi,
        "mp_pct_with_ecgi":      round(report.mp_pct_with_ecgi, 2),
        "plmn_mismatch":         report.plmn_mismatch,
        "plmn_mismatch_examples": report.plmn_mismatch_examples,
        "sample_cell":           report.sample_cell,
        "warnings":              report.warnings,
    }


@router.get("/{project_id}/kpi/{code}")
def kpi_detail(
    project_id: str,
    code: str,
    operator: list[str] = Query(default_factory=list),
    service_type: list[str] = Query(default_factory=list),
    phase: list[str] = Query(default_factory=list),
    group_by: str = Query(default="operator"),
    db: Session = Depends(get_db),
) -> dict:
    _require_project(db, project_id)
    if group_by not in ("operator", "band", "operator_band"):
        raise HTTPException(
            400,
            {
                "code": "GROUP_BY_UNKNOWN",
                "message": f"group_by {group_by!r} invalide. "
                "Valeurs admises : operator | band | operator_band.",
            },
        )
    return compute_kpi_v2(
        db,
        project_id,
        code,
        operators=tuple(operator),
        services=tuple(service_type),
        phases=tuple(phase),
        group_by=group_by,  # type: ignore[arg-type]
    )
