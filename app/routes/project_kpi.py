"""Endpoints KPI scopés projet (0.35.0).

Trois routes publiques (auth lecteur mini, injectée par le router) :
  - GET /projects/{project_id}/kpi/catalog
  - GET /projects/{project_id}/kpi/filters
  - GET /projects/{project_id}/kpi/{code}  (+ query filtres)

Scope `project_id` injecté SERVEUR via le path (jamais depuis le body).
Zéro ligne brute, zéro SQL exposé — tout agrégé. Jamais de valeur
inventée : si une source est indisponible, le statut est renseigné
(UNVALIDATED | PENDING | UNAVAILABLE) et `value` reste `null`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.kpi import KPI_BY_CODE
from app.kpi.service import (
    KpiFilters,
    build_catalog_tree,
    build_filters,
    compute_kpi,
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
def kpi_catalog(project_id: str, db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    return build_catalog_tree(db, project_id)


@router.get("/{project_id}/kpi/filters")
def kpi_filters(project_id: str, db: Session = Depends(get_db)) -> dict:
    _require_project(db, project_id)
    return build_filters(db, project_id)


@router.get("/{project_id}/kpi/{code}")
def kpi_detail(
    project_id: str,
    code: str,
    # Multi-value filters : FastAPI gère `?operator=A&operator=B` ou `operator[]=A`.
    operator: list[str] = Query(default_factory=list),
    rat: list[str] = Query(default_factory=list),
    band: list[str] = Query(default_factory=list),
    service_type: list[str] = Query(default_factory=list),
    env: list[str] = Query(default_factory=list),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
) -> dict:
    _require_project(db, project_id)
    if code not in KPI_BY_CODE:
        raise HTTPException(
            404,
            {
                "code": "KPI_UNKNOWN",
                "message": f"KPI inconnu : {code!r} (voir /kpi/catalog pour la liste)",
            },
        )
    filters = KpiFilters(
        operator=tuple(operator),
        rat=tuple(rat),
        band=tuple(band),
        service_type=tuple(service_type),
        env=tuple(env),
        date_from=date_from,
        date_to=date_to,
    )
    return compute_kpi(db, project_id=project_id, code=code, filters=filters)
