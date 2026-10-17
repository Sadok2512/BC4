"""Routes Dictionnaire v2 (0.45.0) — scope projet.

- GET /projects/{id}/dict/tree?view=catalog|raw
- GET /projects/{id}/dict/distribution?keys=k1,k2&group_by=operator|band|operator_band
- GET /projects/{id}/dict/param/{key}

Pydantic models visibles dans ``/openapi.json`` (``response_model=…``).
Scope strict : ``project_id`` injecté serveur via le path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.dict.service_v2 import (
    build_dict_tree,
    build_distribution,
    build_param_sheet,
)
from app.models import Project
from app.schemas.dict_v2 import (
    DictDistributionResponse,
    DictParamSheet,
    DictTreeResponse,
)


from app.deps import with_statement_timeout_60s

router = APIRouter(
    prefix="/projects",
    tags=["dict-v2"],
    # 0.48.0 — statement_timeout 60 s (cf. project_kpi.router).
    dependencies=[Depends(get_current_user), Depends(with_statement_timeout_60s)],
)


def _require_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(
            404, {"code": "NOT_FOUND", "message": "Projet introuvable"}
        )
    return p


@router.get("/{project_id}/dict/v2/tree", response_model=DictTreeResponse)
def dict_tree(
    project_id: str,
    view: str = Query(default="catalog"),
    db: Session = Depends(get_db),
) -> DictTreeResponse:
    _require_project(db, project_id)
    if view not in ("catalog", "raw"):
        raise HTTPException(
            400,
            {
                "code": "VIEW_UNKNOWN",
                "message": "view attendu ∈ {catalog, raw}",
            },
        )
    return DictTreeResponse(**build_dict_tree(db, project_id, view))


@router.get(
    "/{project_id}/dict/v2/distribution",
    response_model=DictDistributionResponse,
)
def dict_distribution(
    project_id: str,
    keys: str = Query(..., description="Liste CSV de param_key"),
    group_by: str = Query(default="operator"),
    db: Session = Depends(get_db),
) -> DictDistributionResponse:
    _require_project(db, project_id)
    # 0.47.0 — ajoute dor / dr / plaque / arcep_zone (jointure cell_ref).
    allowed = {"operator", "band", "operator_band",
               "dor", "dr", "plaque", "arcep_zone"}
    if group_by not in allowed:
        raise HTTPException(
            400,
            {
                "code": "GROUP_BY_UNKNOWN",
                "message": f"group_by attendu ∈ {sorted(allowed)}",
            },
        )
    key_list = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if not key_list:
        raise HTTPException(
            400,
            {"code": "KEYS_EMPTY", "message": "au moins 1 param_key requis"},
        )
    return DictDistributionResponse(
        **build_distribution(db, project_id, key_list, group_by)
    )


@router.get(
    "/{project_id}/dict/v2/param/{param_key:path}",
    response_model=DictParamSheet,
)
def dict_param(
    project_id: str,
    param_key: str,
    db: Session = Depends(get_db),
) -> DictParamSheet:
    _require_project(db, project_id)
    return DictParamSheet(**build_param_sheet(db, project_id, param_key))
