from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import FilterContext, MeasurementPoint

EvidenceKind = Literal["OBSERVED", "CALCULATED", "INTERPRETED", "UNAVAILABLE"]


class AssistantFilters(BaseModel):
    op: list[str] | None = None
    tech: list[str] | None = None
    svc: list[str] | None = None
    band: list[str] | None = None
    dep: list[str] | None = None


class AssistantRequest(BaseModel):
    project_id: str
    conversation_id: str
    question: str = Field(min_length=1)
    filters: AssistantFilters


class Claim(BaseModel):
    text: str
    kind: EvidenceKind
    source_id: str | None = None


class BlockText(BaseModel):
    type: Literal["text"] = "text"
    heading: str
    claims: list[Claim]


class SummaryItem(BaseModel):
    label: str
    value: float | None
    unit: str
    kind: EvidenceKind
    n: int = Field(ge=0)
    source_id: str


class BlockSummary(BaseModel):
    type: Literal["summary"] = "summary"
    heading: str
    items: list[SummaryItem]


class TableColumn(BaseModel):
    key: str
    label: str
    unit: str | None = None
    numeric: bool | None = None


class BlockTable(BaseModel):
    type: Literal["table"] = "table"
    heading: str
    columns: list[TableColumn]
    rows: list[dict[str, str | float | None]]
    source_id: str
    formula: str | None = None


class ChartSeries(BaseModel):
    name: str
    data: list[float | None | list[float]]


class BlockChart(BaseModel):
    type: Literal["chart"] = "chart"
    chart: Literal["bar", "line", "boxplot"]
    heading: str
    x_label: str
    y_label: str
    unit: str
    categories: list[str]
    series: list[ChartSeries]
    sample_count: int = Field(ge=0)
    source_id: str


class BlockMap(BaseModel):
    type: Literal["map"] = "map"
    heading: str
    metric: Literal["dl", "rsrp", "sinr", "latency"]
    points: list[MeasurementPoint]
    center: tuple[float, float]
    source_id: str


Block = Annotated[
    BlockText | BlockSummary | BlockTable | BlockChart | BlockMap,
    Field(discriminator="type"),
]


class EvidencePeriod(BaseModel):
    start: str
    end: str


class Evidence(BaseModel):
    source_id: str
    source_type: Literal["measurement_points", "rrc_events", "rrc_dictionary"]
    label: str
    sample_count: int = Field(ge=0)
    aggregation: str
    period: EvidencePeriod


class ExecStep(BaseModel):
    id: str
    label: str
    duration_ms: int = Field(ge=0)


class AssistantError(BaseModel):
    code: str
    message: str


class AssistantResponse(BaseModel):
    conversation_id: str
    message_id: str
    status: Literal["completed", "failed", "cancelled"]
    project_id: str
    scenario: str
    effective_filters: AssistantFilters
    blocks: list[Block]
    evidence: list[Evidence]
    follow_ups: list[str]
    execution_steps: list[ExecStep]
    warnings: list[str]
    error: AssistantError | None = None
    demo: Literal[True] = True


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    id: str
    at: str
    text: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    id: str
    at: str
    response: AssistantResponse


ChatMessage = Annotated[UserMessage | AssistantMessage, Field(discriminator="role")]


class Conversation(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage]
