"""SS-03 read-only scope resolution endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_accessible_project, get_current_user
from app.schemas.analysis_scope import AnalysisScope, ResolvedAnalysisScopeOut
from app.services.analysis_scope import resolve_analysis_scope


router = APIRouter(
    prefix="/projects/{project_id}/analysis-scopes",
    tags=["analysis-scopes"],
    dependencies=[Depends(get_current_user), Depends(get_accessible_project)],
)


@router.post("/resolve", response_model=ResolvedAnalysisScopeOut)
def resolve_project_analysis_scope(
    project_id: str,
    scope: AnalysisScope,
    db: Session = Depends(get_db),
) -> ResolvedAnalysisScopeOut:
    """Resolve membership without reading or altering analytical data."""
    return resolve_analysis_scope(db, project_id, scope).as_response()
