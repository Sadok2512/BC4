"""Assistant IA — B0 minimal implementation.

B0 scope ships the contract and the shell so the front can call it; the
real scenario engine lands in B2 (déclaré comme écart ouvert dans
CHANGELOG). The response is built from DB observations (no hardcoded
values); scenario detection is intentionally shallow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import DictMessage, DictParam, ExecStepRow, MeasurementPoint, Project, RrcObservation
from app.schemas.assistant import (
    AssistantFilters,
    AssistantRequest,
    AssistantResponse,
    BlockSummary,
    BlockText,
    Claim,
    Conversation,
    Evidence,
    EvidencePeriod,
    ExecStep,
    SummaryItem,
)

router = APIRouter(
    prefix="/projects",
    tags=["assistant"],
    dependencies=[Depends(get_current_user)],
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_steps(db: Session) -> list[ExecStep]:
    rows = db.query(ExecStepRow).order_by(ExecStepRow.position).all()
    return [ExecStep(id=r.id, label=r.label, duration_ms=r.duration_ms) for r in rows]


@router.post(
    "/{project_id}/assistant",
    response_model=AssistantResponse,
    response_model_exclude_none=True,
)
def post_assistant(
    project_id: str,
    body: AssistantRequest,
    db: Session = Depends(get_db),
) -> AssistantResponse:
    if body.project_id != project_id:
        raise HTTPException(400, {"code": "VALIDATION", "message": "project_id incohérent"})
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})

    q = db.query(MeasurementPoint).filter(MeasurementPoint.project_id == project_id)
    if body.filters.op:
        q = q.filter(MeasurementPoint.operator.in_(body.filters.op))
    if body.filters.tech:
        q = q.filter(MeasurementPoint.tech.in_(body.filters.tech))
    if body.filters.svc:
        q = q.filter(MeasurementPoint.service.in_(body.filters.svc))
    if body.filters.band:
        q = q.filter(MeasurementPoint.band.in_(body.filters.band))
    if body.filters.dep:
        q = q.filter(MeasurementPoint.dep.in_(body.filters.dep))

    sample_count = q.count()
    source_id = "measurement_points.summary"

    message_id = str(uuid.uuid4())
    blocks = [
        BlockText(
            heading="Résumé",
            claims=[
                Claim(
                    text=f"Périmètre : {sample_count} points de mesure correspondent aux filtres.",
                    kind="OBSERVED",
                    source_id=source_id,
                ),
                Claim(
                    text="L'assistant B0 ne couvre pas encore les scénarios de synthèse — écart ouvert (voir CHANGELOG).",
                    kind="UNAVAILABLE",
                ),
            ],
        ),
        BlockSummary(
            heading="Agrégats bruts",
            items=[
                SummaryItem(
                    label="Échantillon filtré",
                    value=float(sample_count),
                    unit="points",
                    kind="OBSERVED",
                    n=sample_count,
                    source_id=source_id,
                ),
            ],
        ),
    ]
    evidence = [
        Evidence(
            source_id=source_id,
            source_type="measurement_points",
            label="Mesures filtrées",
            sample_count=sample_count,
            aggregation="count",
            period=EvidencePeriod(start=project.period_start, end=project.period_end),
        )
    ]
    return AssistantResponse(
        conversation_id=body.conversation_id,
        message_id=message_id,
        status="completed",
        project_id=project_id,
        scenario="b0_sample_count",
        effective_filters=body.filters,
        blocks=blocks,
        evidence=evidence,
        follow_ups=[
            "Comparer les débits par opérateur",
            "Lister les paramètres RRC dominants",
            "Afficher la carte des RSRP",
        ],
        execution_steps=_load_steps(db),
        warnings=["Scénarios complets reportés au lot B2."],
    )


# Conversation history — MOCK-ONLY per Zod comments; B0 returns empty list
# (déclaré écart ouvert, voir CHANGELOG).
@router.get("/{project_id}/conversations", response_model=list[Conversation])
def list_conversations(project_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    if not db.get(Project, project_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return []
