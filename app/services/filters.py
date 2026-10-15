from typing import Iterable

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Query

from app.models import MeasurementPoint, RrcObservation
from app.schemas.common import FilterContext


def apply_measurement_filters(
    query, filters: FilterContext | None = None
):
    """Apply FilterContext filters to a MeasurementPoint query."""
    if not filters:
        return query
    if filters.op:
        query = query.filter(MeasurementPoint.operator.in_(filters.op))
    if filters.tech:
        query = query.filter(MeasurementPoint.tech.in_(filters.tech))
    if filters.svc:
        query = query.filter(MeasurementPoint.service.in_(filters.svc))
    if filters.band:
        query = query.filter(MeasurementPoint.band.in_(filters.band))
    if filters.dep:
        query = query.filter(MeasurementPoint.dep.in_(filters.dep))
    return query


def apply_obs_filters(
    query,
    op: list[str] | None,
    tech: list[str] | None,
    svc: list[str] | None,
    band: list[str] | None,
    dep: list[str] | None,
):
    if op:
        query = query.filter(RrcObservation.operator.in_(op))
    if svc:
        query = query.filter(RrcObservation.service.in_(svc))
    if band:
        query = query.filter(RrcObservation.band.in_(band))
    if dep:
        query = query.filter(RrcObservation.dep.in_(dep))
    # `tech` filter applies to the parent message's techno — applied by join at caller.
    return query


def parse_csv_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or None
