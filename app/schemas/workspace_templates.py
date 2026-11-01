"""Strict v1 contract for durable KPI workspace presentation templates."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartConfiguration(StrictModel):
    kpiCode: str = Field(min_length=1, max_length=255)
    visualization: Literal[
        "histogram", "graph", "table", "map", "task_series", "task_scatter", "chronogram"
    ]
    xMetric: Literal["none", "operator", "band", "operator_band", "dor"]
    yMetric: str = Field(min_length=1, max_length=255)
    groupBy: Literal["none", "operator", "band", "operator_band", "dor"]
    statistic: Literal["value", "p10", "p50", "p90"] | None = None
    curveType: Literal["points", "line", "line_points"] | None = None


class PanelLayoutConfiguration(StrictModel):
    order: list[str] = Field(default_factory=list, max_length=128)
    span: dict[str, Literal[1, 2, 3]] = Field(default_factory=dict, max_length=128)
    height: dict[str, int] = Field(default_factory=dict, max_length=128)
    collapsed: dict[str, bool] = Field(default_factory=dict, max_length=128)
    titles: dict[str, str] = Field(default_factory=dict, max_length=128)
    syncTime: bool = False

    @field_validator("height")
    @classmethod
    def valid_heights(cls, value: dict[str, int]) -> dict[str, int]:
        if any(height < 180 or height > 4000 for height in value.values()):
            raise ValueError("panel heights must be between 180 and 4000")
        return value

    @field_validator("titles")
    @classmethod
    def valid_titles(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not title.strip() or len(title) > 255 for title in value.values()):
            raise ValueError("panel titles must be non-empty and at most 255 characters")
        return value


class TableColorsConfiguration(StrictModel):
    background: str = Field(max_length=32)
    headerBg: str = Field(max_length=32)
    headerText: str = Field(max_length=32)
    rowBg: str = Field(max_length=32)
    altRow: str = Field(max_length=32)
    border: str = Field(max_length=32)
    selected: str = Field(max_length=32)


class TableSortConfiguration(StrictModel):
    col: str = Field(min_length=1, max_length=255)
    dir: Literal["asc", "desc"]


class TableConfiguration(StrictModel):
    perRow: Literal[1, 2, 3]
    autoFitWidth: bool
    equalHeights: bool
    spacing: Literal["compact", "normal", "wide"]
    height: Literal["auto", "fixed", "custom"]
    customHeight: int = Field(ge=200, le=4000)
    hScroll: Literal["auto", "always", "off"]
    resizable: bool
    style: Literal["clean", "professional", "compact"]
    palette: Literal["white", "lightgray", "dark", "blue", "custom"]
    colors: TableColorsConfiguration
    fontSize: Literal["small", "medium", "large"]
    rowHeight: Literal["compact", "normal", "comfortable"]
    headerHeight: Literal["compact", "normal", "large"]
    cellPadding: Literal["small", "medium", "large"]
    borders: Literal["none", "horizontal", "grid"]
    zebra: bool
    stickyHeader: bool
    stickyFirstColumn: bool
    wrap: bool
    cellAlign: Literal["left", "center", "right"]
    numberAlign: Literal["right", "center"]
    radius: Literal["square", "rounded"]
    hidden: list[str] = Field(default_factory=list, max_length=256)
    order: list[str] = Field(default_factory=list, max_length=256)
    showUnits: bool
    sort: TableSortConfiguration | None = None
    # Search is deliberately omitted: it is a temporary filter, not presentation.


class MetricMapLinksConfiguration(StrictModel):
    serving: bool
    neighbour: bool
    nr_anchor: bool


class MetricMapConfiguration(StrictModel):
    palette: Literal["coverage", "viridis", "ocean"]
    pointSize: float = Field(ge=1, le=10)
    links: MetricMapLinksConfiguration


class MetricLegendConfiguration(StrictModel):
    count: int | None = Field(default=None, ge=2, le=8)
    colors: dict[int, str] = Field(default_factory=dict, max_length=8)

    @field_validator("colors")
    @classmethod
    def valid_color_indexes(cls, value: dict[int, str]) -> dict[int, str]:
        if any(index < 0 or index > 7 or len(color) > 32 for index, color in value.items()):
            raise ValueError("legend color index or value is invalid")
        return value


class WorkspaceConfiguration(StrictModel):
    layout: Literal["auto", "1", "2", "3"]
    overlay: bool
    kpiCodes: list[str] = Field(default_factory=list, max_length=100)
    metricCodes: list[str] = Field(default_factory=list, max_length=100)
    activeKpiCode: str | None = Field(default=None, max_length=255)
    chartConfigurations: dict[str, ChartConfiguration] = Field(
        default_factory=dict, max_length=100
    )
    metricViews: dict[str, Literal["graph", "histogram", "table", "map"]] = Field(
        default_factory=dict, max_length=100
    )
    panelLayout: PanelLayoutConfiguration
    tableSettings: TableConfiguration
    metricPane: Literal["charts", "table", "overlay"]
    mapPreferences: dict[str, MetricMapConfiguration] = Field(
        default_factory=dict, max_length=100
    )
    legendSettings: dict[str, MetricLegendConfiguration] = Field(
        default_factory=dict, max_length=100
    )

    @model_validator(mode="after")
    def coherent_codes(self) -> "WorkspaceConfiguration":
        if len(set(self.kpiCodes)) != len(self.kpiCodes):
            raise ValueError("kpiCodes must be unique")
        if len(set(self.metricCodes)) != len(self.metricCodes):
            raise ValueError("metricCodes must be unique")
        if self.activeKpiCode is not None and self.activeKpiCode not in self.kpiCodes:
            raise ValueError("activeKpiCode must belong to kpiCodes")
        if any(key not in self.kpiCodes for key in self.chartConfigurations):
            raise ValueError("chartConfigurations contains an unselected KPI")
        if any(key not in self.metricCodes for key in self.metricViews):
            raise ValueError("metricViews contains an unselected metric")
        if any(key not in self.metricCodes for key in self.mapPreferences):
            raise ValueError("mapPreferences contains an unselected metric")
        return self


class WorkspaceTemplateConfiguration(StrictModel):
    schemaVersion: Literal[1]
    workspace: WorkspaceConfiguration


class WorkspaceTemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    schemaVersion: Literal[1]
    configuration: WorkspaceTemplateConfiguration

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("name is required")
        return clean


class WorkspaceTemplateUpdate(StrictModel):
    description: str | None = Field(default=None, max_length=2000)
    schemaVersion: Literal[1]
    configuration: WorkspaceTemplateConfiguration


class WorkspaceTemplateRename(StrictModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("name is required")
        return clean


class WorkspaceTemplateOut(StrictModel):
    id: str
    projectId: str
    ownerId: str
    name: str
    description: str | None
    schemaVersion: int
    revision: int
    configuration: WorkspaceTemplateConfiguration
    createdAt: datetime
    updatedAt: datetime
