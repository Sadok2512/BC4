"""Schémas Dict v2 (0.45.0) — visibles dans /openapi.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DictView = Literal["catalog", "raw"]
GroupBy = Literal["operator", "band", "operator_band"]
Origin = Literal["network_config", "ue_capability", "ue_report"]


class DictLeaf(BaseModel):
    """Feuille de l'arbre dictionnaire (view=catalog ou view=raw)."""

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


class DictOriginBucket(BaseModel):
    """Origine (``network_config`` | ``ue_capability`` | ``ue_report``)."""
    origin:    Origin
    messages:  list[DictMessageBucket]


class DictTechnoBucket(BaseModel):
    techno:   str
    origins:  list[DictOriginBucket]


class DictTreeResponse(BaseModel):
    project_id:        str
    view:              DictView
    total_rows:        int
    distinct_param_keys: int
    tree:              list[DictTechnoBucket]


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


class DistributionValueGroup(BaseModel):
    """Un groupe (operator ou band ou operator_band) sur une valeur donnée."""
    operator:        str | None = None
    band:            str | None = None
    n:               int
    operator_color:  str | None = None
    band_color:      str | None = None


class DistributionValue(BaseModel):
    value:         str
    value_display: str
    groups:        list[DistributionValueGroup]


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


class DictDistributionResponse(BaseModel):
    project_id: str
    group_by:   GroupBy
    blocks:     list[DistributionBlock]


# ---------------------------------------------------------------------------
# Fiche paramètre
# ---------------------------------------------------------------------------


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
