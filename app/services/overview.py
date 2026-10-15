from collections import defaultdict
from statistics import fmean

from sqlalchemy.orm import Session

from app.models import MeasurementPoint, Project
from app.schemas.common import (
    FilterContext,
    MeasurementPoint as MeasurementPointSchema,
    MetricValue,
    OverviewData,
    OverviewRow,
    Project as ProjectSchema,
    SourceReference,
    TrendPoint,
)
from app.services.filters import apply_measurement_filters


def _project_schema(p: Project) -> ProjectSchema:
    return ProjectSchema(
        id=p.id,
        name=p.name,
        geography=p.geography,
        center=(p.center_lng, p.center_lat),
        operators=p.operators,
        technologies=p.technologies,
        services=p.services,
        bands=p.bands,
        departements=p.departements,
        periodStart=p.period_start,
        periodEnd=p.period_end,
        captures=p.captures,
        importedAt=p.imported_at,
        status=p.status,
    )


def _point_schema(m: MeasurementPoint) -> MeasurementPointSchema:
    return MeasurementPointSchema(
        id=m.id,
        lat=m.lat,
        lng=m.lng,
        operator=m.operator,
        tech=m.tech,
        service=m.service,
        band=m.band,
        dep=m.dep,
        site=m.site,
        ts=m.ts,
        dl=m.dl,
        rsrp=m.rsrp,
        sinr=m.sinr,
        latency=m.latency,
    )


def _mean(vals: list[float | None]) -> tuple[float | None, int, int]:
    v = [x for x in vals if x is not None]
    missing = len(vals) - len(v)
    return (round(fmean(v), 1), len(v), missing) if v else (None, 0, missing)


def compute_overview(db: Session, f: FilterContext) -> OverviewData:
    project = db.get(Project, f.project)
    if not project:
        raise LookupError("project not found")

    q = db.query(MeasurementPoint).filter(MeasurementPoint.project_id == project.id)
    q = apply_measurement_filters(q, f)
    points = q.all()

    def mv(key: str, label: str, unit: str, sel, pop):
        vals = [sel(p) for p in pop]
        value, n, missing = _mean(vals)
        return MetricValue(key=key, label=label, unit=unit, value=value, sampleCount=n, missingCount=missing)

    lte = [p for p in points if p.tech == "LTE"]
    nr = [p for p in points if p.tech != "LTE"]
    endc = [p for p in points if p.tech == "EN-DC"]

    kpis = [
        mv("dl_lte", "Débit DL LTE", "Mbit/s", lambda p: p.dl, lte),
        mv("dl_nr", "Débit DL NR", "Mbit/s", lambda p: p.dl, nr),
        mv("rsrp", "RSRP LTE", "dBm", lambda p: p.rsrp, lte),
        mv("ssrsrp", "SS-RSRP NR", "dBm", lambda p: p.rsrp, nr),
        mv("sinr", "SINR", "dB", lambda p: p.sinr, points),
        mv("latency", "Latence", "ms", lambda p: p.latency, points),
        mv("endc", "Débit EN-DC", "Mbit/s", lambda p: p.dl, endc),
    ]

    by_operator: list[OverviewRow] = []
    for op in project.operators:
        pop = [p for p in points if p.operator == op]
        by_operator.append(
            OverviewRow(
                operator=op,
                samples=len(pop),
                dl=_mean([p.dl for p in pop])[0],
                rsrp=_mean([p.rsrp for p in pop])[0],
                sinr=_mean([p.sinr for p in pop])[0],
                latency=_mean([p.latency for p in pop])[0],
            )
        )

    metric = f.metric or "dl"
    days = sorted({p.ts[:10] for p in points})
    trend: list[TrendPoint] = []
    for day in days:
        series: dict[str, float | None] = {}
        for op in project.operators:
            vals = [
                getattr(p, metric)
                for p in points
                if p.operator == op and p.ts.startswith(day) and getattr(p, metric) is not None
            ]
            series[op] = round(fmean(vals), 1) if vals else None
        trend.append(TrendPoint(day=day, series=series))

    missing = sum(1 for p in points if getattr(p, metric) is None)
    source = SourceReference(
        label=f"Fixture démo — {project.name}",
        population=f"{len(points)} points de mesure filtrés",
        sampleCount=len(points) - missing,
        missingCount=missing,
    )

    return OverviewData(
        project=_project_schema(project),
        points=[_point_schema(p) for p in points],
        kpis=kpis,
        byOperator=by_operator,
        trend=trend,
        source=source,
    )


def project_to_schema(p: Project) -> ProjectSchema:
    return _project_schema(p)
