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
from app.deps import get_current_user
from app.kpi.service_v2 import (
    build_catalog_v2_response,
    build_filters_v2,
    compute_kpi_v2,
)
from app.models import Project


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


@router.get("/{project_id}/kpi/{code}")
def kpi_detail(
    project_id: str,
    code: str,
    operator: list[str] = Query(default_factory=list),
    service_type: list[str] = Query(default_factory=list),
    phase: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    _require_project(db, project_id)
    return compute_kpi_v2(
        db,
        project_id,
        code,
        operators=tuple(operator),
        services=tuple(service_type),
        phases=tuple(phase),
    )
