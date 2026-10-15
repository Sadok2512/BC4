from typing import Literal

from pydantic import BaseModel, Field

Operator = Literal["Orange", "SFR", "Bouygues", "Free"]
Tech = Literal["LTE", "NR", "EN-DC"]
Service = Literal["Data", "SMS", "Voice"]
MetricKey = Literal["dl", "rsrp", "sinr", "latency"]
ProjectStatus = Literal["ready", "processing", "failed"]


class Project(BaseModel):
    id: str
    name: str
    geography: str
    center: tuple[float, float]
    operators: list[Operator]
    technologies: list[Tech]
    services: list[Service]
    bands: list[str]
    departements: list[str]
    periodStart: str
    periodEnd: str
    captures: int
    importedAt: str
    status: ProjectStatus


class FilterContext(BaseModel):
    project: str | None = None
    op: list[Operator] | None = None
    tech: list[Tech] | None = None
    svc: list[Service] | None = None
    band: list[str] | None = None
    dep: list[str] | None = None
    metric: MetricKey | None = None


class SourceReference(BaseModel):
    label: str
    population: str
    sampleCount: int
    missingCount: int
    demo: Literal[True] = True


class MetricValue(BaseModel):
    key: str
    label: str
    unit: str
    value: float | None
    sampleCount: int
    missingCount: int


class MeasurementPoint(BaseModel):
    id: str
    lat: float
    lng: float
    operator: Operator
    tech: Tech
    service: Service
    band: str
    dep: str
    site: str
    ts: str
    dl: float | None
    rsrp: float | None
    sinr: float | None
    latency: float | None


class OverviewRow(BaseModel):
    operator: Operator
    samples: int
    dl: float | None
    rsrp: float | None
    sinr: float | None
    latency: float | None


class TrendPoint(BaseModel):
    day: str
    series: dict[str, float | None] = Field(default_factory=dict)


class OverviewData(BaseModel):
    project: Project
    points: list[MeasurementPoint]
    kpis: list[MetricValue]
    byOperator: list[OverviewRow]
    trend: list[TrendPoint]
    source: SourceReference


class ApiError(BaseModel):
    code: str
    message: str
