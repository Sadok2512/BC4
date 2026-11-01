"""Certified procedure reconstruction and KPI endpoints."""

from __future__ import annotations

import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_accessible_project, get_current_user, with_statement_timeout_60s
from app.procedures.catalog import BY_CODE, CATALOG, aggregate, catalog_tree
from app.procedures.engine import Procedure
from app.procedures.service import procedures_for_scope


router = APIRouter(
    prefix="/projects",
    tags=["procedures"],
    dependencies=[
        Depends(get_current_user),
        Depends(get_accessible_project),
        Depends(with_statement_timeout_60s),
    ],
)


class ProcedureRow(BaseModel):
    procedure_id: str
    project_id: str
    capture_id: str
    ue_key: str
    session_key: str
    rat: str
    procedure_type: str
    start_seq: int
    end_seq: int | None
    start_time: str | None
    end_time: str | None
    duration_ms: float | None
    source_pci: int | None
    source_arfcn: int | None
    target_pci: int | None
    target_arfcn: int | None
    bearer_id: int | None
    ebi: int | None
    qci: int | None
    qfi: int | None
    five_qi: int | None
    s_nssai: str | None
    result: Literal["ATTEMPT", "SUCCESS", "FAILURE", "ABNORMAL_RELEASE", "DROP", "TIMEOUT", "UNKNOWN"]
    failure_cause: str | None
    evidence_level: Literal["PROVEN", "PROBABLE", "UNKNOWN"]
    source_event_ids: list[str]
    latitude: float | None
    longitude: float | None
    gps_seq: int | None
    signaling_url: str


def _capture_scope(db: Session, project_id: str, capture_ids: list[str]) -> list[str]:
    project = db.execute(text("SELECT 1 FROM projects WHERE id=:project_id"), {"project_id": project_id}).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, {"code": "PROJECT_NOT_FOUND", "message": "Project not found."})
    existing = list(
        db.execute(
            text(
                """SELECT capture_id FROM nmf_capture
                   WHERE project_id=:project_id
                   ORDER BY project_id,capture_id"""
            ),
            {"project_id": project_id},
        ).scalars()
    )
    if not capture_ids:
        return existing
    requested = list(dict.fromkeys(capture_ids))
    unknown = [capture_id for capture_id in requested if capture_id not in set(existing)]
    if unknown:
        raise HTTPException(
            422,
            {"code": "CAPTURE_SCOPE_INVALID", "message": "Capture does not belong to project.", "unknown": unknown},
        )
    return requested


def _row(procedure: Procedure) -> dict:
    value = procedure.as_dict()
    value["signaling_url"] = (
        f"/projects/{procedure.project_id}/signaling?capture={procedure.capture_id}"
        f"&seq={procedure.start_seq}&procedure={procedure.procedure_id}"
    )
    return value


@router.get("/{project_id}/procedures/catalog")
def procedure_catalog(
    project_id: str,
    capture_id: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    captures = _capture_scope(db, project_id, capture_id)
    procedures = procedures_for_scope(db, project_id, captures)
    return {
        "project_id": project_id,
        "capture_ids": captures,
        "engine_version": "procedure-v1",
        **catalog_tree(procedures),
    }


@router.get("/{project_id}/procedures/kpis")
def procedure_kpis(
    project_id: str,
    capture_id: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    captures = _capture_scope(db, project_id, capture_id)
    procedures = procedures_for_scope(db, project_id, captures)
    return {
        "project_id": project_id,
        "capture_ids": captures,
        "engine_version": "procedure-v1",
        "kpis": [
            {
                **aggregate(definition, procedures),
                "name": definition.name,
                "technology": definition.technology,
                "family": definition.family,
                "unit": definition.unit,
                "description": definition.description,
                "minimum_evidence": definition.minimum_evidence,
            }
            for definition in CATALOG
        ],
    }


@router.get("/{project_id}/procedures/kpis/{code}")
def procedure_kpi(
    project_id: str,
    code: str,
    capture_id: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    definition = BY_CODE.get(code)
    if definition is None:
        raise HTTPException(404, {"code": "PROCEDURE_KPI_NOT_FOUND", "message": "Procedure KPI not found."})
    captures = _capture_scope(db, project_id, capture_id)
    procedures = procedures_for_scope(db, project_id, captures)
    summary = aggregate(definition, procedures)
    return {
        **summary,
        "project_id": project_id,
        "capture_ids": captures,
        "name": definition.name,
        "technology": definition.technology,
        "family": definition.family,
        "unit": definition.unit,
        "description": definition.description,
        "minimum_evidence": definition.minimum_evidence,
        "formula": (
            "100 × SUCCESS / (SUCCESS + FAILURE), UNKNOWN excluded"
            if definition.measure == "rate"
            else definition.measure
        ),
        "population": "Ordered capture-local procedures matching the selected procedure types.",
        "exclusions": "Evidence below minimum level and UNKNOWN outcomes are excluded from rate denominators.",
    }


@router.get("/{project_id}/procedures", response_model=None)
def list_procedures(
    project_id: str,
    capture_id: list[str] = Query(default_factory=list),
    procedure_type: list[str] = Query(default_factory=list),
    result: list[str] = Query(default_factory=list),
    evidence_level: list[str] = Query(default_factory=list),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    captures = _capture_scope(db, project_id, capture_id)
    procedures = procedures_for_scope(db, project_id, captures)
    selected = [
        procedure
        for procedure in procedures
        if (not procedure_type or procedure.procedure_type in procedure_type)
        and (not result or procedure.result in result)
        and (not evidence_level or procedure.evidence_level in evidence_level)
    ]
    start = (page - 1) * size
    return {
        "project_id": project_id,
        "capture_ids": captures,
        "engine_version": "procedure-v1",
        "total": len(selected),
        "page": page,
        "size": size,
        "pages": math.ceil(len(selected) / size),
        "rows": [_row(procedure) for procedure in selected[start : start + size]],
    }


@router.get("/{project_id}/procedures/{procedure_id}", response_model=ProcedureRow)
def procedure_detail(
    project_id: str,
    procedure_id: str,
    capture_id: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
) -> dict:
    captures = _capture_scope(db, project_id, capture_id)
    procedure = next(
        (row for row in procedures_for_scope(db, project_id, captures) if row.procedure_id == procedure_id),
        None,
    )
    if procedure is None:
        raise HTTPException(404, {"code": "PROCEDURE_NOT_FOUND", "message": "Procedure not found in scope."})
    return _row(procedure)
