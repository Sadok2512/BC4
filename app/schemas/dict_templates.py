"""Validated, project-independent template configuration and project-scoped results."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.schemas.dict_v2 import DistributionValue

class ParameterRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    param_key: str = Field(min_length=1, max_length=2048)
    technology: Literal['LTE','NR']
    discriminators: dict[str, str | bool | int] = Field(default_factory=dict)

class TemplateEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=100)
    label: str = Field(min_length=1,max_length=160)
    position: int = Field(ge=0)
    technology: Literal['LTE','NR']
    discriminators: dict[str, str | bool | int] = Field(default_factory=dict)
    parameters: list[ParameterRef] = Field(default_factory=list,max_length=100)
    reason: str | None = None

class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    entries: list[TemplateEntry] = Field(max_length=200)

    @model_validator(mode='after')
    def unique(self):
        if len({x.id for x in self.entries}) != len(self.entries):
            raise ValueError('Duplicate entry ids')
        for entry in self.entries:
            refs=[(x.technology,x.param_key,str(sorted(x.discriminators.items()))) for x in entry.parameters]
            if len(set(refs)) != len(refs): raise ValueError('Duplicate parameter references')
            for i, left in enumerate(entry.parameters):
                for right in entry.parameters[i+1:]:
                    if left.technology == right.technology and left.param_key == right.param_key:
                        shared = left.discriminators.keys() & right.discriminators.keys()
                        if all(left.discriminators[k] == right.discriminators[k] for k in shared):
                            raise ValueError('Overlapping parameter populations')
            if any(x.technology != entry.technology for x in entry.parameters): raise ValueError('Technology mismatch')
        return self

class TemplateRow(TemplateEntry):
    n_in_project: int
    resolved: bool

class TemplateCategory(BaseModel):
    id: str
    label: str
    position: int
    revision: int
    n_parameters: int
    n_in_project: int
    entries: list[TemplateRow]

class TemplatesResponse(BaseModel):
    project_id: str
    categories: list[TemplateCategory]

class SummaryCell(BaseModel):
    operator: str | None = None
    band: str | None = None
    n: int
    missing_value_n: int
    dominant_values: list[str]
    dominant_value: str | None
    percentage: float | None
    differs_from_majority: bool | None = None

class SummaryRow(BaseModel):
    entry_id: str
    label: str
    param_key: str | None
    technology: str
    discriminators: dict
    n_in_project: int
    resolved: bool
    reason: str | None = None
    distribution: list[DistributionValue]
    cells: list[SummaryCell]
    result_id: str

class SummaryResponse(BaseModel):
    project_id: str
    category_id: str
    group_by: Literal['operator','band','operator_band']
    rows: list[SummaryRow]
