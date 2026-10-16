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
    # 0.22.3 — libellé d'affichage désambigué pour l'arbre `/dict/tree`.
    # Égal à la feuille (`leaf`) du path quand ce leaf est unique dans
    # `(system, message)`. En cas de collision (ex. plusieurs
    # `rsrpResult` sous `MeasurementReport`), suffixé par le premier
    # ancêtre distinctif entre parenthèses, ex.
    # `"rsrpResult (measResultPCell)"` vs `"rsrpResult (measResult)"`.
    # Jamais inventé — dérivé 100% du path. Non-breaking (champ additif
    # tolere par le Zod front, cf. non-régression `value_distribution`
    # 0.15.0 et `value_matrix` 0.21.0). Le champ `param` reste le path
    # complet non suffixé (clé stable pour `/dict/params?path=…` et
    # `/dict/param/map`).
    label: str = ""


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


# 0.15.0 — distribution par valeur d'un paramètre
# ---------------------------------------------------------
# Pour un paramètre numérique (unit_converted non null), on groupe par
# (value_raw, value_converted) et on trie par value_converted ascendant
# (float). Pour un paramètre enum (unit_converted null), on groupe par
# value_raw et on trie alpha ascendant ; value_converted est null.
# Si le nombre de valeurs numériques distinctes dépasse
# `VALUE_DISTRIBUTION_BINNING_THRESHOLD` (100), on binne par pas régulier
# (1 unité dans l'unité convertie, ex. 1 dBm pour rsrp) : value_raw et
# value_converted portent la borne `[lo, hi)` et `mode = "binned"` au
# niveau de l'item. Sinon `mode = "exact"`. Aucune invention : si la
# valeur n'est pas en base, elle n'apparaît pas.
class ValueBucket(BaseModel):
    value_raw: str
    value_converted: str | None = None
    count: int = Field(ge=0)


ValueDistributionMode = Literal["exact", "binned"]


# 0.18.0 — Value matrix (value × operator × band)
# ---------------------------------------------------------
# Table croisée exposée pour chaque paramètre : chaque cellule donne,
# pour un `(value_raw, value_converted, operator, band)`, le `count`.
# `operator` et `band` sont des chaînes jamais nulles ("non attribué"
# remplace NULL — jamais inventées depuis `operators_plmn` ou
# `freq`/`pci`). Le front consomme ce champ pour afficher le
# « regroupement par opérateur × bande » (grouping.ts) qui était
# désactivé en 0.15.0 faute de donnée exposée en cross-table.
class ValueMatrixCell(BaseModel):
    value_raw: str
    value_converted: str | None = None
    operator: str
    band: str
    count: int = Field(ge=0)


class ParamRow(BaseModel):
    system: Literal["LTE", "NR"]
    message: str
    path: str
    count: int = Field(ge=0)
    unit_converted: str | None = None
    buckets: list[ParamBucket]
    # 0.15.0 — ajout non-breaking : distribution par valeur du paramètre.
    value_distribution: list[ValueBucket] = Field(default_factory=list)
    value_distribution_mode: ValueDistributionMode = "exact"
    # 0.18.0 — ajout non-breaking : table croisée value × operator × band.
    value_matrix: list[ValueMatrixCell] = Field(default_factory=list)


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
