from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConversionRule(BaseModel):
    formula: str
    scale: float
    offset: float
    unit: str
    decimals: int
    ref: str


class GeoNode(BaseModel):
    id: str
    label: str
    level: Literal["plaque", "dr", "departement", "site"]
    children: list["GeoNode"] = Field(default_factory=list)


GeoNode.model_rebuild()


class DictDimensions(BaseModel):
    operators: list[str]
    services: list[str]
    technos: list[str]
    bands: list[str]
    geo_tree: list[GeoNode]
    periods: list[str]


class DictProject(BaseModel):
    id: str
    dimensions: DictDimensions


class TreeMessage(BaseModel):
    msg_id: str
    name: str
    count: int = Field(ge=0)


class TreeChannel(BaseModel):
    name: str
    messages: list[TreeMessage]


class TreeBranch(BaseModel):
    techno: Literal["LTE", "NR"]
    channels: list[TreeChannel]


class DictTree(BaseModel):
    branches: list[TreeBranch]


class Dominant(BaseModel):
    value: str | float | None
    conversion: str | None
    share: float | None = Field(default=None, ge=0, le=1)


class ParamSummary(BaseModel):
    param_id: str
    leaf: str
    path: str
    n: int = Field(ge=0)
    distinct: int = Field(ge=0)
    dominant: Dominant


class ParamList(BaseModel):
    params: list[ParamSummary]


class ParamFiche(BaseModel):
    techno: Literal["LTE", "NR"]
    message: str
    path: str
    leaf: str
    type: str
    dominant: Dominant
    conversion_rule: ConversionRule | None


class HistogramBin(BaseModel):
    label: str
    value_num: float | None
    count: int = Field(ge=0)


class MatrixCell(BaseModel):
    bin_index: int = Field(ge=0)
    pct: float = Field(ge=0, le=100)
    n: int = Field(ge=0)


class MatrixRow(BaseModel):
    key: str
    total: int = Field(ge=0)
    cells: list[MatrixCell]


class ParamMatrix(BaseModel):
    bins: list[str]
    rows: list[MatrixRow]


class ParamDetail(BaseModel):
    fiche: ParamFiche
    histogram: list[HistogramBin]
    matrix: ParamMatrix


class MapPointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class MapPointProperties(BaseModel):
    value: float | str
    display: str


class MapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: MapPointGeometry
    properties: MapPointProperties


class LegendStop(BaseModel):
    value: float
    label: str


class LegendClass(BaseModel):
    value: str
    label: str


class MapLegend(BaseModel):
    kind: Literal["numeric", "categorical"]
    stops: list[LegendStop] | None = None
    classes: list[LegendClass] | None = None


class ParamMap(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[MapFeature]
    legend: MapLegend


GroupBy = Literal["operator", "band", "operator,band"]


# --------------------------------------------------------------------- #
# 0.12.0 — Dictionnaire complet RRC LTE+NR
#
# Schémas Pydantic DÉDIÉS aux endpoints `/dict/*` branchés sur
# `param_occurrence`. Les schémas B0 ci-dessus (DictTree / ParamList /
# ParamMap / ParamDetail) restent exposés pour les routes historiques
# (`/dict/param/map`, `/dict/param`) qui lisent `rrc_observations` seedés.
# Les trois nouvelles routes utilisent des types différents (arbre à
# 2 branches racines → messages → paths ; histogrammes `(operator, band)`;
# occurrences géolocalisées). Zod/Pydantic 1:1 côté front dans le lot 1.7.0.
# --------------------------------------------------------------------- #


class DictTreeParam(BaseModel):
    param: str
    count: int = Field(ge=0)


class DictTreeMessage(BaseModel):
    message: str
    count: int = Field(ge=0)
    params: list[DictTreeParam]


class DictTreeBranch(BaseModel):
    system: Literal["LTE", "NR"]
    count: int = Field(ge=0)
    messages: list[DictTreeMessage]


class DictTreeV2(BaseModel):
    """Nouvel arbre : LTE/NR → message → path (feuille = {param, count})."""

    branches: list[DictTreeBranch]


class ParamBucket(BaseModel):
    operator: str | None = None
    band: str | None = None
    count: int = Field(ge=0)
    avg_converted: float | None = None


class ParamRow(BaseModel):
    system: Literal["LTE", "NR"]
    message: str
    path: str
    count: int = Field(ge=0)
    unit_converted: str | None = None
    buckets: list[ParamBucket]


class ParamListV2(BaseModel):
    params: list[ParamRow]


class ParamMapPoint(BaseModel):
    lat: float
    lon: float
    value_raw: str | None = None
    value_converted: str | None = None
    operator: str | None = None
    band: str | None = None


class ParamMapV2(BaseModel):
    path: str
    system: Literal["LTE", "NR"]
    points: list[ParamMapPoint]
