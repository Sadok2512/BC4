from typing import Literal

from pydantic import BaseModel, Field
from app.schemas.ingest import NmfImportJobView

Operator = Literal["Orange", "SFR", "Bouygues", "Free"]
Tech = Literal["LTE", "NR", "EN-DC"]
Service = Literal["Data", "SMS", "Voice"]
MetricKey = Literal["dl", "rsrp", "sinr", "latency"]
ProjectStatus = Literal["ready", "processing", "failed"]
# 0.46.0 — Complétude ingest↔populate :
#   `ready`      : tous les NMF ingérés ont été populés, `n_points > 0`.
#   `incomplete` : NMF ingérés sans populate (ou n_points=0 malgré fichiers).
#   `processing` : ingest en cours.
#   `empty`      : aucun NMF.
#   `failed`     : erreur bloquante.
ProjectIngestStatus = Literal["ready", "incomplete", "processing", "empty", "failed"]


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
    # 0.46.0 — Visibilité complétude côté client (dashboard /projects).
    # Jamais inventé : `n_files` = COUNT(nmf_file.status='done'), `n_points`
    # = snapshot stocké au dernier populate (NULL si pas encore passé).
    # `last_populate_at` ISO 8601 ; `ingest_status` dérivé (voir ci-dessus).
    import_job: NmfImportJobView | None = None
    n_files: int = 0
    n_points: int | None = None
    last_populate_at: str | None = None
    ingest_status: ProjectIngestStatus = "empty"


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
    lat: float | None
    lng: float | None
    operator: Operator | None
    tech: Tech | None
    service: Service | None
    band: str | None
    dep: str | None
    site: str | None
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
