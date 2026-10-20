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
    temporal_source: Optional[str] = Field(None, description="Source temporelle autorisée pour la vue Série ; null si source agrégée ou absente")
    formula: Optional[str] = None
    service_scope: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: KpiStatus
    reason: Optional[str] = Field(..., description="raison si status ≠ AVAILABLE, sinon null")
    # 0.64.0 (F1) — enrichissement contrat pour les 2 onglets KPI/Métriques
    category: Optional[str] = Field(None, description="7 catégories BC4 (Accessibilité, Rétention, Mobilité, Débit, Latence, Voix, Couverture & qualité)")
    metric_sources: list[str] = Field(default_factory=list, description="codes NMF ou événements sources dont le KPI dérive")
    available: bool = Field(False, description="raccourci booléen = (status == 'AVAILABLE')")


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


class KpiGroupByOption(BaseModel):
    """0.47.0 — Déclare quels `group_by` sont utilisables sur ce projet.

    `operator` / `band` / `operator_band` sont toujours vrais. `dor` /
    `dr` / `plaque` / `arcep_zone` dépendent du peuplement de cell_ref
    sur les cellules observées (ECGI strict). `available=false` →
    `reason` obligatoire (jamais muet)."""
    model_config = ConfigDict(extra="allow")
    key: str
    available: bool
    reason: Optional[str] = None


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
    # 0.47.0 — Déclare les group_by utilisables (operator/band toujours ;
    # dor/dr/plaque/arcep_zone selon état du cell_ref).
    group_by_options: list[KpiGroupByOption] = Field(default_factory=list)


class KpiGroupRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    n: int
    operator: Optional[str] = None
    band: Optional[str] = None
    # 0.47.0 — Jointure cell_ref (dor/dr/plaque/arcep_zone). `"N/D"`
    # littéral quand l'ECGI est manquant / non strict / sans valeur
    # dans cell_ref.
    dor: Optional[str] = None
    dr: Optional[str] = None
    plaque: Optional[str] = None
    arcep_zone: Optional[str] = None
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
    # 0.47.0 — Couverture jointure cell_ref (dor/dr/plaque/arcep_zone).
    # with_value = n points avec ECGI strict ET valeur présente dans
    # cell_ref ; total = n points totaux ; pct = with_value / total.
    coverage: Optional[dict] = None
    # Déclare les group_by utilisables sur ce projet (idem /kpi/filters).
    group_by_options: Optional[list[KpiGroupByOption]] = None
