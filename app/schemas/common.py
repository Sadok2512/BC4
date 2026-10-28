from typing import Literal

from pydantic import BaseModel, Field
from app.schemas.ingest import NmfImportJobView

# Les Literal ci-dessous décrivent le CATALOGUE des opérateurs/technos/services
# connus. Ils restent utiles pour la documentation OpenAPI et pour les filtres
# applicatifs internes, mais ils NE DOIVENT PAS valider les champs alimentés
# par l'ingestion : un NMF réel peut contenir un PLMN non catalogué (ex.
# "PLMN 208-08"), un service encore inconnu, une techno hors liste. Dans ce
# cas la valeur brute passe par la chaîne, est affichée en gris côté front
# avec tooltip "détecté dans les logs, non présent dans le catalogue" — rien
# n'est renommé ni supprimé. Les champs listés dans Project/MeasurementPoint/
# OverviewRow/FilterContext utilisent donc `str` au lieu de ces Literal.
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
    owner_id: str
    visibility: Literal["private", "public"]
    parse_decode_level: Literal["light", "deep"]
    parse_binning_mode: Literal["temporal", "spatial"]
    parse_temporal_resolution: Literal["native", "1ms", "10ms", "100ms", "1s"] | None
    parse_spatial_bin_m: Literal[10, 25, 50, 100] | None
    name: str
    geography: str
    center: tuple[float, float]
    # Alimentés par l'ingestion. `str` ouvert : un NMF peut contenir une
    # valeur hors catalogue (ex. "PLMN 208-08"), auquel cas elle est
    # transmise brute sans être renommée ni supprimée.
    operators: list[str]
    technologies: list[str]
    services: list[str]
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
    # Mêmes règles que Project : le filtre peut viser un opérateur/techno/
    # service non catalogué (découvert à l'ingestion). Pas de rejet 422.
    op: list[str] | None = None
    tech: list[str] | None = None
    svc: list[str] | None = None
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
    # Alimentés par l'ingestion → str ouvert, cf. Project.operators.
    operator: str | None
    tech: str | None
    service: str | None
    band: str | None
    dep: str | None
    site: str | None
    ts: str
    dl: float | None
    rsrp: float | None
    sinr: float | None
    latency: float | None


class OverviewRow(BaseModel):
    # Alimenté par l'agrégation issue de l'ingestion → str ouvert, cf. Project.
    operator: str
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
