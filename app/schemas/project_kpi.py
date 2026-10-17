"""Pydantic response_model pour les 3 routes `/projects/{id}/kpi/*`.

Deux objectifs :
  1. Exposer un `$ref` dans `/openapi.json` → le front peut typer la
     réponse et `bun run contract:check` peut comparer via OpenAPI (plus
     seulement via live safeParse).
  2. Rendre le champ `source` **obligatoire** sur toute réponse KPI →
     plus un seul chiffre sans sa source déclarée (règle n°2 BC4).

`extra='allow'` partout : nouvel attribut back → le front ne casse pas
(règle front 1.17.3). On garantit juste la **présence** des champs
critiques (`code`, `name`, `nature`, `status`, `source`, …).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


KpiStatus = Literal["AVAILABLE", "PENDING", "UNVALIDATED", "UNAVAILABLE", "NOT_APPLICABLE"]


class KpiCatalogItem(BaseModel):
    """Entrée KPI dans l'arbre catalogue."""
    model_config = ConfigDict(extra="allow")

    code: str = Field(..., description="code canonique du KPI (catalogue v2)")
    name: str
    nature: str
    unit: Optional[str] = Field(..., description="unité physique ou null si N/A")
    source: Optional[str] = Field(
        ...,
        description="source back (table.col, path RRC, formule) — jamais omis",
    )
    formula: Optional[str] = None
    service_scope: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: KpiStatus
    reason: Optional[str] = Field(..., description="raison si status ≠ AVAILABLE, sinon null")


class KpiCatalogFamily(BaseModel):
    model_config = ConfigDict(extra="allow")
    family: str
    kpis: list[KpiCatalogItem]


class KpiCatalogTechno(BaseModel):
    model_config = ConfigDict(extra="allow")
    techno: str
    families: list[KpiCatalogFamily]


class ProjectKpiCatalog(BaseModel):
    """Réponse GET /projects/{id}/kpi/catalog."""
    model_config = ConfigDict(extra="allow")

    project_id: str
    catalog_version: str
    canonical_count: Optional[int] = None
    aliases_count: Optional[int] = None
    counts_by_status: Optional[dict[str, int]] = None
    counts_by_techno: Optional[dict[str, dict[str, int]]] = None
    tree: list[KpiCatalogTechno]


class KpiFilterDimension(BaseModel):
    model_config = ConfigDict(extra="allow")
    available: bool
    reason: Optional[str] = None
    values: list[str] = Field(default_factory=list)


class ProjectKpiFilters(BaseModel):
    """Réponse GET /projects/{id}/kpi/filters.

    Chaque dim est optionnelle (règle front 1.17.3) + passthrough — un
    champ en plus ne casse rien.
    """
    model_config = ConfigDict(extra="allow")

    project_id: str
    operators: Optional[KpiFilterDimension] = None
    rats: Optional[KpiFilterDimension] = None
    bands: Optional[KpiFilterDimension] = None
    service_types: Optional[KpiFilterDimension] = None
    envs: Optional[KpiFilterDimension] = None
    deps: Optional[KpiFilterDimension] = None
    phases: Optional[KpiFilterDimension] = None
    ecgi: Optional[KpiFilterDimension] = None
    dr: Optional[KpiFilterDimension] = None
    plaque: Optional[KpiFilterDimension] = None
    dor: Optional[KpiFilterDimension] = None
    arcep: Optional[KpiFilterDimension] = None
    commune: Optional[KpiFilterDimension] = None
    insee: Optional[KpiFilterDimension] = None


class KpiGroupRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    n: int
    operator: Optional[str] = None
    band: Optional[str] = None
    p10: Optional[float] = None
    p50: Optional[float] = None
    p90: Optional[float] = None
    status: Optional[str] = None
    reason: Optional[str] = None


class ProjectKpiDetail(BaseModel):
    """Réponse GET /projects/{id}/kpi/{code}.

    Garantie : `source` est TOUJOURS présent (jamais null, jamais omis).
    Un KPI sans source back est un bug — pas une valeur à afficher.
    """
    model_config = ConfigDict(extra="allow")

    requested_code: Optional[str] = None
    code: Optional[str] = None
    name: Optional[str] = None
    techno: Optional[str] = None
    family: Optional[str] = None
    nature: Optional[str] = None
    unit: Optional[str] = None
    formula: Optional[str] = None
    source: str = Field(..., description="source back obligatoire — règle n°2 BC4")
    service_scope: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: KpiStatus
    reason: Optional[str] = None
    value: Optional[float] = None
    n: Optional[int] = None
    p10: Optional[float] = None
    p50: Optional[float] = None
    p90: Optional[float] = None
    group_by: Optional[str] = None
    groups: Optional[list[KpiGroupRow]] = None
    table: Optional[list[KpiGroupRow]] = None
