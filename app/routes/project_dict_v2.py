"""Routes Dictionnaire v2 (0.45.0) — scope projet.

- GET /projects/{id}/dict/tree?view=catalog|raw
- GET /projects/{id}/dict/distribution?keys=k1,k2&group_by=operator|band|operator_band
- GET /projects/{id}/dict/param/{key}

Pydantic models visibles dans ``/openapi.json`` (``response_model=…``).
Scope strict : ``project_id`` injecté serveur via le path.
"""

from __future__ import annotations

from typing import Literal
from collections import OrderedDict
from copy import deepcopy
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import get_db
from app.deps import get_current_user
from app.dict.service_v2 import (
    build_dict_tree,
    build_distribution,
    build_param_sheet,
)
from app.dict.signaling_message import decoded_message
from app.schemas.signaling_message import SignalingMessage
from app.dict.geo_filters import geographic_options
from app.kpi.catalog_release.registry import current_catalog
from app.models import Project
from app.schemas.dict_v2 import (
    DictMapResponse,
    DictFilterOptions,
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

DICT_TREE_VERSION = "dict-v2-catalog-1"
_TREE_CACHE = OrderedDict()
_TREE_CACHE_LOCK = Lock()
_TREE_BUILD_LOCK = Lock()


def _tree_stamp(db: Session, project_id: str) -> tuple:
    # Every import finalization publishes a new dictionary generation after all
    # param_occurrence writes. Reading this single PK row replaces the former
    # COUNT/MAX scan on the whole project.
    row = db.execute(text("""SELECT generation,total_occurrences,
      distinct_param_keys,summary_rows FROM dict_network_catalog_state
      WHERE project_id=:pid"""), {"pid": project_id}).one_or_none()
    return tuple(row) if row is not None else ("not-materialized",)


def _catalog_tree(db: Session, project_id: str) -> dict:
    release = current_catalog(db)
    key = (project_id, release.version if release else DICT_TREE_VERSION)
    stamp = _tree_stamp(db, project_id)
    with _TREE_CACHE_LOCK:
        cached = _TREE_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            _TREE_CACHE.move_to_end(key)
            return deepcopy(cached[1])
    with _TREE_BUILD_LOCK:
        with _TREE_CACHE_LOCK:
            cached = _TREE_CACHE.get(key)
            if cached is not None and cached[0] == stamp:
                _TREE_CACHE.move_to_end(key)
                return deepcopy(cached[1])
        value = build_dict_tree(db, project_id, "catalog", None)
        with _TREE_CACHE_LOCK:
            _TREE_CACHE[key] = (stamp, value)
            _TREE_CACHE.move_to_end(key)
            while len(_TREE_CACHE) > 16:
                _TREE_CACHE.popitem(last=False)
    return deepcopy(value)


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
    message: str | None = Query(default=None),
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
    if view == "catalog" and message is None:
        # build_dict_tree already emits the DictTreeResponse contract and the
        # cached object is immutable to callers (deep-copied by _catalog_tree).
        # Returning a Response skips a second full Pydantic walk over ~1 MB.
        return JSONResponse(content=_catalog_tree(db, project_id))
    value = build_dict_tree(db, project_id, view, message)
    return DictTreeResponse(**value)


@router.get("/{project_id}/dict/v2/filters", response_model=DictFilterOptions)
def dict_filter_options(project_id: str, db: Session = Depends(get_db)) -> DictFilterOptions:
    _require_project(db, project_id)
    return DictFilterOptions(**geographic_options(db, project_id))


@router.get(
    "/{project_id}/dict/v2/distribution",
    response_model=DictDistributionResponse,
)
def dict_distribution(
    project_id: str,
    keys: str = Query(..., description="Liste CSV de param_key"),
    group_by: str = Query(default="operator"),
    technology: Literal["LTE", "NR"] | None = Query(default=None),
    dor: list[str] | None = Query(default=None),
    plaque: list[str] | None = Query(default=None),
    arcep_zone: list[str] | None = Query(default=None),
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
    if technology and group_by not in {"operator", "band", "operator_band"}:
        raise HTTPException(422, detail={"code": "TECHNOLOGY_GROUP_UNSUPPORTED", "message": "Filtre technologique : regroupement par opérateur, bande ou les deux."})
    key_list = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if not key_list:
        raise HTTPException(
            400,
            {"code": "KEYS_EMPTY", "message": "au moins 1 param_key requis"},
        )
    geographic = {key: tuple(values) for key, values in {"dor": dor, "plaque": plaque, "arcep_zone": arcep_zone}.items() if values}
    if geographic and group_by not in {"operator", "band", "operator_band"}:
        raise HTTPException(422, detail={"code": "GROUP_BY_UNSUPPORTED_WITH_FILTERS", "message": "Filtres géographiques : regroupement par opérateur, bande ou les deux."})
    return DictDistributionResponse(
        **build_distribution(db, project_id, key_list, group_by, geographic=geographic, technology=technology)
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


@router.get("/{project_id}/dict/v2/map", response_model=DictMapResponse)
def dict_map(
    project_id: str,
    keys: str = Query(..., max_length=20000),
    technology: Literal["LTE", "NR"] | None = Query(default=None),
    operator: list[str] | None = Query(default=None),
    band: list[str] | None = Query(default=None),
    dor: list[str] | None = Query(default=None),
    plaque: list[str] | None = Query(default=None),
    arcep_zone: list[str] | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> DictMapResponse:
    from app.dict.map_v2 import build_map
    _require_project(db, project_id)
    key_list = sorted(set(k.strip() for k in keys.split(',') if k.strip()))
    if not key_list or len(key_list) > 100:
        raise HTTPException(422, detail={"code": "MAP_KEYS_INVALID", "message": "Sélectionnez entre 1 et 100 paramètres."})
    geographic = {key: tuple(values) for key, values in {"dor": dor, "plaque": plaque, "arcep_zone": arcep_zone}.items() if values}
    return DictMapResponse(**build_map(db, project_id, key_list, technology=technology,
        operators=operator or (), bands=band or (), geographic=geographic, limit=limit))


# Templates: project identity is always supplied by the route, never by configuration.
from typing import Literal
from app.schemas.dict_templates import TemplatesResponse, SummaryResponse
from app.dict.templates import list_templates, summarize, template_metadata
from app.kpi.catalog_cache import CatalogCache

# Reuse the existing bounded, single-flight cache implementation.
# Only template-list responses are retained, separately from KPI entries.
_template_list_cache = CatalogCache(ttl=30, capacity=64)

@router.get("/{project_id}/dict/v2/templates", response_model=TemplatesResponse)
def dict_templates(project_id: str, include_counts: bool = True, db: Session = Depends(get_db)):
    _require_project(db, project_id)
    if not include_counts:
        return template_metadata(db, project_id)
    return _template_list_cache.get(project_id, lambda: list_templates(db, project_id))

@router.get("/{project_id}/dict/v2/templates/{category}/summary", response_model=SummaryResponse)
def dict_template_summary(project_id: str, category: str, group_by: Literal["operator", "band", "operator_band"] = "operator", keys: str | None = None, db: Session = Depends(get_db)):
    _require_project(db, project_id)
    return summarize(db, project_id, category, group_by, [k for k in keys.split(",") if k] if keys else None)


# Kept on the authenticated dictionary router: no shared router registration change.
@router.get('/{project_id}/signaling/message', response_model=SignalingMessage)
def signaling_message(
    project_id: str,
    capture_id: str = Query(..., min_length=1, max_length=128),
    seq: int = Query(..., ge=0),
    db: Session = Depends(get_db),
) -> SignalingMessage:
    _require_project(db, project_id)
    return decoded_message(db, project_id, capture_id, seq)
