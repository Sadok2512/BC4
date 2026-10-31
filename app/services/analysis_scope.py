"""Secure SS-03 resolver shared by future analytical engines.

This module resolves scope membership only. It deliberately does not query,
merge or renumber events; Signaling, Metrics and Map keep their existing
capture engines until their dedicated integration lots.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.analysis_scope import (
    AnalysisScope,
    CaptureAnalysisScope,
    ResolvedAnalysisMember,
    ResolvedAnalysisScopeOut,
)


@dataclass(frozen=True)
class ResolvedAnalysisScope:
    project_id: str
    scope: AnalysisScope
    scope_revision: int | None
    members: tuple[ResolvedAnalysisMember, ...]

    def member_position(self, capture_id: str) -> int:
        """Return a position only for a capture proven to belong to the scope."""
        for member in self.members:
            if member.captureId == capture_id:
                return member.memberPosition
        raise KeyError(capture_id)

    def order_key(self, capture_id: str, seq: int) -> tuple[int, int]:
        """Canonical cross-capture order; timestamps are intentionally absent."""
        return self.member_position(capture_id), seq

    def as_response(self) -> ResolvedAnalysisScopeOut:
        return ResolvedAnalysisScopeOut(
            projectId=self.project_id,
            scope=self.scope,
            scopeRevision=self.scope_revision,
            members=self.members,
        )


def _not_found() -> HTTPException:
    # Same response for an unknown id and an id owned by another project: no
    # cross-project existence oracle.
    return HTTPException(
        404,
        {"code": "ANALYSIS_SCOPE_NOT_FOUND", "message": "Périmètre analytique introuvable."},
    )


def resolve_analysis_scope(
    db: Session,
    project_id: str,
    scope: AnalysisScope,
) -> ResolvedAnalysisScope:
    """Resolve capture members under an explicit project boundary."""
    if isinstance(scope, CaptureAnalysisScope):
        capture_id = db.execute(
            text(
                "SELECT capture_id FROM nmf_capture "
                "WHERE project_id=:pid AND capture_id=:capture_id"
            ),
            {"pid": project_id, "capture_id": scope.captureId},
        ).scalar_one_or_none()
        if capture_id is None:
            raise _not_found()
        members = (
            ResolvedAnalysisMember(
                projectId=project_id,
                captureId=str(capture_id),
                memberPosition=0,
            ),
        )
        return ResolvedAnalysisScope(project_id, scope, None, members)

    stream = db.execute(
        text(
            "SELECT id, revision FROM superstream "
            "WHERE id=:scope_id AND project_id=:pid"
        ),
        {"scope_id": scope.superstreamId, "pid": project_id},
    ).one_or_none()
    if stream is None:
        raise _not_found()
    rows = db.execute(
        text(
            "SELECT m.capture_id, m.position "
            "FROM superstream_member m "
            "JOIN nmf_capture c ON c.project_id=m.project_id AND c.capture_id=m.capture_id "
            "WHERE m.superstream_id=:scope_id AND m.project_id=:pid "
            "ORDER BY m.position"
        ),
        {"scope_id": scope.superstreamId, "pid": project_id},
    ).all()
    if not rows:
        raise HTTPException(
            409,
            {
                "code": "ANALYSIS_SCOPE_EMPTY",
                "message": "Le Superstream ne contient aucune capture.",
            },
        )
    members = tuple(
        ResolvedAnalysisMember(
            projectId=project_id,
            captureId=str(capture_id),
            memberPosition=int(position),
        )
        for capture_id, position in rows
    )
    return ResolvedAnalysisScope(project_id, scope, int(stream.revision), members)
