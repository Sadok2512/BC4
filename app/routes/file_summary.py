"""Traceable file summaries for the Projects file listing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Project
from app.routes.tasks import evidence
from app.services.file_summary import EVENTS, summarize_file

router = APIRouter(dependencies=[Depends(get_current_user)], tags=["projects"])


class SummaryCell(BaseModel):
    value: str | float | int | None
    n: int | None
    max: float | None
    unit: str | None
    source_event: str
    reason: str | None
    query_id: str


class FileSummaryRow(BaseModel):
    file_id: str
    filename: str
    cells: dict[str, SummaryCell]


class FileSummaryResponse(BaseModel):
    project_id: str
    offset: int
    limit: int
    total: int
    query_id: str
    files: list[FileSummaryRow]

FILE_SQL = """SELECT id,filename,uploaded_at
FROM nmf_file
WHERE project_id=:pid
ORDER BY uploaded_at,filename
OFFSET :offset LIMIT :limit"""

EVENT_SQL = """SELECT c.nmf_file_id,c.capture_id,c.kind,NULL::integer seq,NULL::varchar event_code,
       NULL::varchar system,'{}'::jsonb raw_fields
FROM nmf_capture c
WHERE c.project_id=:pid AND c.nmf_file_id=ANY(:file_ids)
UNION ALL
SELECT r.nmf_file_id,c.capture_id,c.kind,r.seq,r.event_code,r.system,
       jsonb_build_object('service_action',r.raw_fields->>'service_action',
                          'c4',r.raw_fields->>'c4','c5',r.raw_fields->>'c5',
                          'c6',r.raw_fields->>'c6','c8',r.raw_fields->>'c8',
                          'c9',r.raw_fields->>'c9','c11',r.raw_fields->>'c11') raw_fields
FROM stg_event_raw r
JOIN nmf_capture c ON c.project_id=r.project_id AND c.capture_id=r.capture_id
                    AND c.nmf_file_id=r.nmf_file_id
WHERE r.project_id=:pid AND r.nmf_file_id=ANY(:file_ids) AND r.event_code=ANY(:events)
ORDER BY nmf_file_id,capture_id,seq NULLS FIRST"""


@router.get("/projects/{project_id}/files/summary", response_model=FileSummaryResponse)
def file_summary(
    project_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    if not db.get(Project, project_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    params = {"pid": project_id, "offset": offset, "limit": limit}
    files = [dict(row) for row in db.execute(text(FILE_SQL), params).mappings()]
    total = int(db.execute(text("SELECT count(*) FROM nmf_file WHERE project_id=:pid"), {"pid": project_id}).scalar() or 0)
    by_file: dict[str, list[dict]] = {row["id"]: [] for row in files}
    if files:
        event_params = {"pid": project_id, "file_ids": list(by_file), "events": sorted(EVENTS)}
        for row in db.execute(text(EVENT_SQL), event_params).mappings():
            by_file[str(row["nmf_file_id"])].append(dict(row))
    available_events = set(db.execute(text(
        "SELECT DISTINCT event_code FROM stg_event_raw "
        "WHERE project_id=:pid AND event_code=ANY(:events)"
    ), {"pid": project_id, "events": sorted(EVENTS)}).scalars())
    summaries = [summarize_file(row, by_file[row["id"]], available_events) for row in files]
    query_id = evidence(
        db, project_id,
        FILE_SQL + ";\n" + EVENT_SQL,
        {**params, "file_ids": list(by_file), "events": sorted(EVENTS)},
        {"files": len(files), "total": total, "offset": offset, "limit": limit},
    )
    for summary in summaries:
        for cell in summary["cells"].values():
            cell["query_id"] = query_id
    return {"project_id": project_id, "offset": offset, "limit": limit, "total": total,
            "query_id": query_id, "files": summaries}
