"""Shared SS-03 analysis-scope contract.

The scope selects captures only. Event identity remains the immutable
``(project_id, capture_id, seq)`` tuple and is never replaced by a synthetic
Superstream sequence.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaptureAnalysisScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["capture"]
    captureId: str = Field(min_length=1)


class SuperstreamAnalysisScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["superstream"]
    superstreamId: str = Field(min_length=1)


AnalysisScope = Annotated[
    CaptureAnalysisScope | SuperstreamAnalysisScope,
    Field(discriminator="type"),
]


class ResolvedAnalysisMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    projectId: str
    captureId: str
    memberPosition: int = Field(ge=0)


class ResolvedAnalysisScopeOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    projectId: str
    scope: AnalysisScope
    scopeRevision: int | None
    members: tuple[ResolvedAnalysisMember, ...]
    identityFields: tuple[Literal["project_id", "capture_id", "seq"], ...] = (
        "project_id",
        "capture_id",
        "seq",
    )
    orderFields: tuple[Literal["member_position", "seq"], ...] = (
        "member_position",
        "seq",
    )
