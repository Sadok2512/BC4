"""Schémas Dict v2 (0.45.0) — visibles dans /openapi.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DictView = Literal["catalog", "raw"]
# 0.47.0 — Ajoute `dor` (join mp.ecgi → cell_ref.dor, ecgi_source=
# 'sib1_strict' uniquement). Mécanique prête pour `dr` / `plaque` /
# `arcep_zone` (déclarés mais désactivés côté front tant que les
# colonnes correspondantes ne sont pas peuplées sur cell_ref).
GroupBy = Literal[
    "operator", "band", "operator_band",
    "dor", "dr", "plaque", "arcep_zone",
]
Origin = Literal["network_config", "ue_capability", "ue_report"]


class DictLeaf(BaseModel):
    """Feuille de l'arbre dictionnaire (view=catalog ou view=raw)."""

    category_id: str | None = None
    param_key:        str
    display_name:     str
    unit:             str | None = None
    choice_of:        str | None = None
    discriminators:   dict | None = None
    origin:           Origin | None = None
    is_identifier:    bool = False
    n:                int
    sample_paths:     list[str] = Field(default_factory=list, description="Jusqu'à 3 chemins ASN.1 bruts (view=raw).")


class DictGroup(BaseModel):
    """Groupe fonctionnel (ex. ``MAC-DRX``, ``Mesures critères``)."""
    name:  str
    kpis:  list[DictLeaf]


class DictMessageBucket(BaseModel):
    """Message porteur (ex. ``RRCConnectionReconfiguration``)."""
    message: str
    groups:  list[DictGroup]


class DictCatalogLeaf(DictLeaf):
    message: str | None = None
    subcategory_id: str | None = None
    discriminator: dict = Field(default_factory=dict)
    n_occurrences: int
    n_captures: int
    n_in_tech: int
    source_param_keys: list[str] = Field(default_factory=list)


class DictParameterNode(BaseModel):
    param_key: str
    display_name: str
    unit: str | None = None
    category_id: str
    subcategory_id: str | None = None
    n: int
    n_occurrences: int
    n_captures: int
    n_in_tech: int
    leaves: list[DictCatalogLeaf]


class DictSubcategoryNode(BaseModel):
    id: str | None
    label: str
    position: int
    parameters: list[DictParameterNode]


class DictCategoryNode(BaseModel):
    id: str
    label: str
    position: int
    subcategories: list[DictSubcategoryNode]


class DictOriginBucket(BaseModel):
    """Origine (``network_config`` | ``ue_capability`` | ``ue_report``)."""
    origin:    Origin
    messages:  list[DictMessageBucket] = Field(default_factory=list)
    categories: list[DictCategoryNode] = Field(default_factory=list)


class DictTechnoBucket(BaseModel):
    techno:   str
    origins:  list[DictOriginBucket]


class DictTreeResponse(BaseModel):
    project_id:        str
    view:              DictView
    available_messages: list[str] = Field(default_factory=list)
    total_rows:        int
    distinct_param_keys: int
    tree:              list[DictTechnoBucket]
    # Forward ref — défini plus bas (GroupByOption).
    group_by_options:  list["GroupByOption"] = Field(
        default_factory=list,
        description="0.47.0 — group_by disponibles pour ce projet (operator/band/operator_band toujours ; dor/dr/plaque/arcep_zone selon état de cell_ref).",
    )


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


class DistributionValueGroup(BaseModel):
    """Un groupe (operator / band / operator_band / dor / dr / plaque /
    arcep_zone) sur une valeur donnée.

    0.47.0 — Ajout de ``dor`` + ``dr`` / ``plaque`` / ``arcep_zone``
    pour exposer la jointure cell_ref. ``operator`` / ``band`` restent
    là pour compatibilité avec les anciens appels. ``N/D`` = valeur
    littérale ``"N/D"`` dans la colonne concernée quand l'ECGI est
    absent, non strict, ou que la cellule n'a pas la valeur dans
    cell_ref — jamais filtré silencieusement."""
    operator:        str | None = None
    band:            str | None = None
    dor:             str | None = None
    dr:              str | None = None
    plaque:          str | None = None
    arcep_zone:      str | None = None
    n:               int
    operator_color:  str | None = None
    band_color:      str | None = None


class DistributionValue(BaseModel):
    value:         str
    value_display: str
    groups:        list[DistributionValueGroup]


class DistributionBlockStatus(BaseModel):
    """0.47.0 — Déclaration d'indisponibilité pour un `group_by` requis.

    Quand `group_by=dor` (ou dr/plaque/arcep_zone) mais que le
    référentiel cellule n'expose pas la dimension pour ce projet, on
    renvoie le bloc avec `status='UNAVAILABLE'` + `reason` lisible. Les
    `values` restent `[]`, `verdict=NON_COMPARE`. **Jamais filtré
    silencieusement**.
    """
    status: Literal["UNAVAILABLE"]
    reason: str


class DistributionCoverage(BaseModel):
    """0.47.0 — Couverture de la jointure cell_ref pour un `group_by`
    dimensionnel (dor/dr/plaque/arcep_zone). Permet au front d'afficher
    « N points sur M dans un DOR connu (X %) »."""
    with_value:    int
    total:         int
    pct:           float


class DistributionBlock(BaseModel):
    param_key:      str
    display_name:   str
    unit:           str | None
    choice_of:      str | None = None
    discriminators: dict | None = None
    origin:         Origin
    n_total:        int
    distinct_values: int
    values:         list[DistributionValue]
    comparability:  str
    verdict:        Literal["IDENTIQUE", "DIFFERENT", "NON_COMPARE"]
    result_id:      str
    source_result_id: str | None = None
    status:         Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    reason:         str | None = None
    coverage:       DistributionCoverage | None = None


class GroupByOption(BaseModel):
    """0.47.0 — Déclaration côté catalogue des `group_by` disponibles
    pour un projet. `available=false` → `reason` obligatoire."""
    key:        GroupBy
    available:  bool
    reason:     str | None = None


class DictDistributionResponse(BaseModel):
    project_id:        str
    group_by:          GroupBy
    blocks:            list[DistributionBlock]
    group_by_options:  list[GroupByOption] = Field(
        default_factory=list,
        description="Déclare quels group_by sont utilisables sur ce projet (cell_ref peuplé ou non).",
    )


# ---------------------------------------------------------------------------
# Fiche paramètre
# ---------------------------------------------------------------------------


# Résout la forward ref `DictTreeResponse.group_by_options -> GroupByOption`.
DictTreeResponse.model_rebuild()


class DictParamSheet(BaseModel):
    project_id:        str
    param_key:         str
    display_name:      str
    unit:              str | None
    choice_of:         str | None = None
    discriminators_examples: list[dict] = Field(default_factory=list)
    origin:            Origin
    source:            str
    carrying_messages: list[dict] = Field(default_factory=list, description="[{message, n}]")
    n_total:           int
    sample_paths:      list[str] = Field(default_factory=list)
    kpi_hint:          str | None = Field(default=None, description="Pour origin=ue_report : code KPI correspondant (ex. LTE_RF_RSRP_AT_MR).")


class DictGeographicDimension(BaseModel):
    key: Literal["dor", "plaque", "arcep_zone"]
    label: str
    available: bool
    reason: str | None = None
    options: list[str]
    count: int


class DictFilterOptions(BaseModel):
    project_id: str
    geographic: list[DictGeographicDimension]


class DictMapPoint(BaseModel):
    occurrence_id: str
    event_id: str
    capture_id: str
    seq: int
    nmf_file_id: str | None
    param_key: str
    display_name: str | None
    path: str
    technology: str
    operator: str | None
    band: str | None
    value_raw: str | None
    value_converted: str | None
    unit: str | None
    lat: float
    lon: float
    source: str
    coordinate_source: str
    operator_color: str


class DictMapOperator(BaseModel):
    name: str
    count: int
    color: str


class DictMapResponse(BaseModel):
    project_id: str
    points: list[DictMapPoint]
    total_occurrences: int
    geolocated_occurrences: int
    returned_occurrences: int
    truncated: bool
    limit: int
    operators: list[DictMapOperator]
    reason: str | None
