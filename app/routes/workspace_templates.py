"""Durable personal KPI workspace templates, isolated by project and owner."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_accessible_project, get_current_user
from app.models import AppUser, WorkspaceTemplate
from app.schemas.workspace_templates import (
    WorkspaceTemplateConfiguration,
    WorkspaceTemplateCreate,
    WorkspaceTemplateOut,
    WorkspaceTemplateRename,
    WorkspaceTemplateUpdate,
)


router = APIRouter(
    prefix="/projects/{project_id}/workspace-templates",
    tags=["workspace-templates"],
    dependencies=[Depends(get_current_user), Depends(get_accessible_project)],
)


def _expected_revision(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(
            428,
            {"code": "PRECONDITION_REQUIRED", "message": "If-Match est obligatoire."},
        )
    raw = if_match.strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    try:
        revision = int(raw)
    except ValueError as exc:
        raise HTTPException(
            400,
            {"code": "INVALID_IF_MATCH", "message": "If-Match doit contenir une révision entière."},
        ) from exc
    if revision < 1:
        raise HTTPException(
            400,
            {"code": "INVALID_IF_MATCH", "message": "La révision doit être positive."},
        )
    return revision


def _set_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = f'"{revision}"'


def _description(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _serialize(row: WorkspaceTemplate) -> WorkspaceTemplateOut:
    return WorkspaceTemplateOut(
        id=row.id,
        projectId=row.project_id,
        ownerId=row.owner_id,
        name=row.name,
        description=row.description,
        schemaVersion=row.schema_version,
        revision=row.revision,
        configuration=WorkspaceTemplateConfiguration.model_validate(row.configuration),
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _owned(
    db: Session, project_id: str, owner_id: str, template_id: str
) -> WorkspaceTemplate:
    row = (
        db.query(WorkspaceTemplate)
        .filter(
            WorkspaceTemplate.id == template_id,
            WorkspaceTemplate.project_id == project_id,
            WorkspaceTemplate.owner_id == owner_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            404,
            {"code": "WORKSPACE_TEMPLATE_NOT_FOUND", "message": "Template introuvable."},
        )
    return row


def _raise_missing_or_revision_conflict(
    db: Session,
    project_id: str,
    owner_id: str,
    template_id: str,
    expected: int,
) -> None:
    current = db.execute(
        text(
            "SELECT revision FROM workspace_template "
            "WHERE id=:template_id AND project_id=:pid AND owner_id=:owner_id"
        ),
        {"template_id": template_id, "pid": project_id, "owner_id": owner_id},
    ).scalar_one_or_none()
    if current is None:
        raise HTTPException(
            404,
            {"code": "WORKSPACE_TEMPLATE_NOT_FOUND", "message": "Template introuvable."},
        )
    raise HTTPException(
        409,
        {
            "code": "REVISION_CONFLICT",
            "message": "Le template a été modifié ; rechargez-le avant de réessayer.",
            "expected": expected,
            "current": int(current),
        },
    )


@router.get("", response_model=list[WorkspaceTemplateOut])
def list_workspace_templates(
    project_id: str,
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> list[WorkspaceTemplateOut]:
    rows = (
        db.query(WorkspaceTemplate)
        .filter(
            WorkspaceTemplate.project_id == project_id,
            WorkspaceTemplate.owner_id == current.id,
        )
        .order_by(WorkspaceTemplate.updated_at.desc(), WorkspaceTemplate.id)
        .all()
    )
    return [_serialize(row) for row in rows]


@router.post("", response_model=WorkspaceTemplateOut, status_code=201)
def create_workspace_template(
    project_id: str,
    body: WorkspaceTemplateCreate,
    response: Response,
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> WorkspaceTemplateOut:
    now = datetime.now(timezone.utc)
    row = WorkspaceTemplate(
        id=str(uuid.uuid4()),
        project_id=project_id,
        owner_id=current.id,
        name=body.name,
        description=_description(body.description),
        schema_version=body.schemaVersion,
        revision=1,
        configuration=body.configuration.model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            {"code": "NAME_CONFLICT", "message": "Un template du même nom existe déjà."},
        ) from exc
    db.refresh(row)
    _set_etag(response, row.revision)
    return _serialize(row)


@router.get("/{template_id}", response_model=WorkspaceTemplateOut)
def get_workspace_template(
    project_id: str,
    template_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> WorkspaceTemplateOut:
    row = _owned(db, project_id, current.id, template_id)
    _set_etag(response, row.revision)
    return _serialize(row)


@router.put("/{template_id}", response_model=WorkspaceTemplateOut)
def update_workspace_template(
    project_id: str,
    template_id: str,
    body: WorkspaceTemplateUpdate,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> WorkspaceTemplateOut:
    expected = _expected_revision(if_match)
    now = datetime.now(timezone.utc)
    result = db.execute(
        text("""
            UPDATE workspace_template
            SET description=:description,
                schema_version=:schema_version,
                configuration=CAST(:configuration AS jsonb),
                updated_at=:updated_at,
                revision=revision+1
            WHERE id=:template_id AND project_id=:pid AND owner_id=:owner_id
              AND revision=:expected
            RETURNING revision
        """),
        {
            "description": _description(body.description),
            "schema_version": body.schemaVersion,
            "configuration": body.configuration.model_dump_json(),
            "updated_at": now,
            "template_id": template_id,
            "pid": project_id,
            "owner_id": current.id,
            "expected": expected,
        },
    ).scalar_one_or_none()
    if result is None:
        db.rollback()
        _raise_missing_or_revision_conflict(
            db, project_id, current.id, template_id, expected
        )
    db.commit()
    row = _owned(db, project_id, current.id, template_id)
    _set_etag(response, row.revision)
    return _serialize(row)


@router.patch("/{template_id}/name", response_model=WorkspaceTemplateOut)
def rename_workspace_template(
    project_id: str,
    template_id: str,
    body: WorkspaceTemplateRename,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> WorkspaceTemplateOut:
    expected = _expected_revision(if_match)
    try:
        result = db.execute(
            text("""
                UPDATE workspace_template
                SET name=:name, updated_at=:updated_at, revision=revision+1
                WHERE id=:template_id AND project_id=:pid AND owner_id=:owner_id
                  AND revision=:expected
                RETURNING revision
            """),
            {
                "name": body.name,
                "updated_at": datetime.now(timezone.utc),
                "template_id": template_id,
                "pid": project_id,
                "owner_id": current.id,
                "expected": expected,
            },
        ).scalar_one_or_none()
        if result is None:
            db.rollback()
            _raise_missing_or_revision_conflict(
                db, project_id, current.id, template_id, expected
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            {"code": "NAME_CONFLICT", "message": "Un template du même nom existe déjà."},
        ) from exc
    row = _owned(db, project_id, current.id, template_id)
    _set_etag(response, row.revision)
    return _serialize(row)


@router.delete("/{template_id}", status_code=204)
def delete_workspace_template(
    project_id: str,
    template_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
    current: AppUser = Depends(get_current_user),
) -> Response:
    expected = _expected_revision(if_match)
    result = db.execute(
        text("""
            DELETE FROM workspace_template
            WHERE id=:template_id AND project_id=:pid AND owner_id=:owner_id
              AND revision=:expected
            RETURNING id
        """),
        {
            "template_id": template_id,
            "pid": project_id,
            "owner_id": current.id,
            "expected": expected,
        },
    ).scalar_one_or_none()
    if result is None:
        db.rollback()
        _raise_missing_or_revision_conflict(
            db, project_id, current.id, template_id, expected
        )
    db.commit()
    return Response(status_code=204)
