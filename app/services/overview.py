from collections import defaultdict, namedtuple
from statistics import fmean

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.models import MeasurementPoint, NmfFile, Project, NmfImportJob
from app.services.import_jobs import job_view
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


_POINT_FIELDS = ("id", "lat", "lng", "operator", "tech", "service", "band", "dep",
                 "site", "ts", "dl", "rsrp", "sinr", "latency")
_OverviewPoint = namedtuple("_OverviewPoint", _POINT_FIELDS)
_POINT_LIST = TypeAdapter(list[MeasurementPointSchema])


def _ingest_status(n_files: int, n_points: int | None, status_ingest: str | None) -> str:
    """Dérive l'état complétude à partir de l'état DB observé.

    Jamais inventé : lit uniquement `nmf_file.status='done'` (via n_files),
    `projects.n_points` (snapshot populate), `projects.status_ingest`.
    """
    if status_ingest in ("importing", "processing"):
        return "processing"
    if status_ingest == "error":
        return "failed"
    if n_files == 0:
        return "empty"
    # NMF ingérés : vérifier le populate.
    if n_points is None or n_points == 0:
        return "incomplete"
    return "ready"


def _project_schema(p: Project) -> ProjectSchema:
    # 0.46.0 — Dérivation `n_files` + `ingest_status` à la volée depuis la DB.
    # `n_files` = COUNT(nmf_file WHERE status='done') ; une seule requête par
    # projet. Si pas de session rattachée (projet mocké), on tombe à 0 sans
    # inventer.
    db = object_session(p)
    n_files = 0
    if db is not None:
        n_files = (
            db.query(NmfFile).filter(NmfFile.project_id == p.id, NmfFile.status == "done").count()
        )
    latest_job = (db.query(NmfImportJob).filter(NmfImportJob.project_id == p.id)
        .order_by(NmfImportJob.created_at.desc()).first()) if db is not None else None
    status = _ingest_status(n_files, p.n_points, p.status_ingest)
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
        n_files=n_files,
        import_job=job_view(latest_job) if latest_job else None,
        n_points=p.n_points,
        last_populate_at=p.last_populate_at.isoformat() if p.last_populate_at else None,
        ingest_status=status,  # type: ignore[arg-type]
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

    # Scalar rows avoid materializing hundreds of thousands of ORM identities
    # and unused ingestion columns. The returned point population is unchanged.
    q = db.query(*(getattr(MeasurementPoint, key) for key in _POINT_FIELDS)).filter(
        MeasurementPoint.project_id == project.id
    )
    q = apply_measurement_filters(q, f)
    # SQLAlchemy Row attribute lookup dominates millions of accesses here.
    # Compact tuples give constant-time field descriptors; fetch batches avoid
    # keeping an additional full DB result/ORM population in memory.
    points = [_OverviewPoint(*row) for row in q.yield_per(10000)]

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
    # Index each observation once, rather than scanning the full population
    # again for every day/operator pair. Keep input order and fmean rounding.
    buckets = defaultdict(lambda: defaultdict(list))
    for point in points:
        day = buckets[point.ts[:10]]
        value = getattr(point, metric)
        if value is not None:
            day[point.operator].append(value)
    trend: list[TrendPoint] = []
    for day in sorted(buckets):
        series = {}
        for op in project.operators:
            vals = buckets[day].get(op, [])
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
        points=_POINT_LIST.validate_python(points, from_attributes=True),
        kpis=kpis,
        byOperator=by_operator,
        trend=trend,
        source=source,
    )


def project_to_schema(p: Project) -> ProjectSchema:
    return _project_schema(p)
