from collections import defaultdict
from statistics import mean

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.models import ConversionRule, DictMessage, DictParam, Project, RrcObservation
from app.schemas.dictionary import (
    ConversionRule as ConversionRuleSchema,
    DictDimensions,
    DictProject,
    DictTree,
    Dominant,
    GeoNode,
    HistogramBin,
    LegendClass,
    LegendStop,
    MapFeature,
    MapLegend,
    MapPointGeometry,
    MapPointProperties,
    MatrixCell,
    MatrixRow,
    ParamDetail,
    ParamFiche,
    ParamList,
    ParamMap,
    ParamMatrix,
    ParamSummary,
    TreeBranch,
    TreeChannel,
    TreeMessage,
)
from app.schemas.common import FilterContext


def _geo_tree_for_project(project: Project) -> list[GeoNode]:
    """Minimal geo tree built from departements. B2 will plug the real referential."""
    children = [
        GeoNode(id=f"{project.id}-dep-{dep}", label=f"Département {dep}", level="departement", children=[])
        for dep in project.departements
    ]
    return [GeoNode(id=f"{project.id}-plaque", label=project.geography, level="plaque", children=children)]


def build_dict_project(project: Project) -> DictProject:
    period = f"{project.period_start}/{project.period_end}"
    return DictProject(
        id=project.id,
        dimensions=DictDimensions(
            operators=project.operators,
            services=project.services,
            technos=[t for t in project.technologies if t in ("LTE", "NR")],
            bands=project.bands,
            geo_tree=_geo_tree_for_project(project),
            periods=[period],
        ),
    )


def build_dict_tree(
    db: Session,
    project: Project,
    filters: FilterContext | None = None,
) -> DictTree:
    """Always expose LTE and NR branches (invariant from the Zod refinement),
    even if the project has no NR observations — those channels/messages come
    back with count=0 and the UI renders the empty state."""
    q = (
        db.query(
            DictMessage.techno,
            DictMessage.channel,
            DictMessage.msg_id,
            DictMessage.name,
            func.count(RrcObservation.id).label("count"),
        )
        .select_from(DictMessage)
        .join(DictParam, DictParam.msg_id == DictMessage.msg_id)
        .outerjoin(
            RrcObservation,
            (RrcObservation.param_id == DictParam.param_id)
            & (RrcObservation.project_id == project.id),
        )
    )

    if filters:
        if filters.op:
            q = q.filter((RrcObservation.operator.in_(filters.op)) | (RrcObservation.id.is_(None)))
        if filters.svc:
            q = q.filter((RrcObservation.service.in_(filters.svc)) | (RrcObservation.id.is_(None)))
        if filters.band:
            q = q.filter((RrcObservation.band.in_(filters.band)) | (RrcObservation.id.is_(None)))
        if filters.dep:
            q = q.filter((RrcObservation.dep.in_(filters.dep)) | (RrcObservation.id.is_(None)))
        if filters.tech:
            q = q.filter(DictMessage.techno.in_(filters.tech))

    rows = q.group_by(DictMessage.techno, DictMessage.channel, DictMessage.msg_id, DictMessage.name).all()

    # Group by techno → channel → messages
    by_techno: dict[str, dict[str, list[TreeMessage]]] = {"LTE": defaultdict(list), "NR": defaultdict(list)}
    for techno, channel, msg_id, name, count in rows:
        by_techno[techno][channel].append(TreeMessage(msg_id=msg_id, name=name, count=int(count)))

    branches: list[TreeBranch] = []
    for techno in ("LTE", "NR"):
        channels = [
            TreeChannel(name=channel, messages=sorted(msgs, key=lambda m: m.msg_id))
            for channel, msgs in sorted(by_techno[techno].items())
        ]
        branches.append(TreeBranch(techno=techno, channels=channels))

    return DictTree(branches=branches)


def _convert(rule: ConversionRule | None, raw: float | int | None) -> str | None:
    if rule is None or raw is None:
        return None
    v = raw * rule.scale + rule.offset
    return f"{v:.{rule.decimals}f} {rule.unit}".replace(".", ",")


def _dominant(db: Session, project_id: str, param: DictParam, rule: ConversionRule | None) -> Dominant:
    if param.spec_kind == "numeric":
        q = (
            db.query(RrcObservation.raw_num, func.count(RrcObservation.id))
            .filter(RrcObservation.project_id == project_id, RrcObservation.param_id == param.param_id)
            .group_by(RrcObservation.raw_num)
            .order_by(func.count(RrcObservation.id).desc())
            .first()
        )
        total = (
            db.query(func.count(RrcObservation.id))
            .filter(RrcObservation.project_id == project_id, RrcObservation.param_id == param.param_id)
            .scalar()
            or 0
        )
        if not q or total == 0:
            return Dominant(value=None, conversion=None, share=None)
        val, cnt = q
        return Dominant(value=val, conversion=_convert(rule, val), share=round(cnt / total, 3))
    else:
        q = (
            db.query(RrcObservation.raw_str, func.count(RrcObservation.id))
            .filter(RrcObservation.project_id == project_id, RrcObservation.param_id == param.param_id)
            .group_by(RrcObservation.raw_str)
            .order_by(func.count(RrcObservation.id).desc())
            .first()
        )
        total = (
            db.query(func.count(RrcObservation.id))
            .filter(RrcObservation.project_id == project_id, RrcObservation.param_id == param.param_id)
            .scalar()
            or 0
        )
        if not q or total == 0:
            return Dominant(value=None, conversion=None, share=None)
        val, cnt = q
        return Dominant(value=val, conversion=None, share=round(cnt / total, 3))


def build_param_list(
    db: Session, project: Project, msg_id: str, filters: FilterContext | None = None
) -> ParamList:
    msg = db.get(DictMessage, msg_id)
    if not msg:
        return ParamList(params=[])
    params = db.query(DictParam).filter(DictParam.msg_id == msg_id).all()

    summaries: list[ParamSummary] = []
    for p in params:
        base_q = db.query(RrcObservation).filter(
            RrcObservation.project_id == project.id,
            RrcObservation.param_id == p.param_id,
        )
        if filters:
            if filters.op:
                base_q = base_q.filter(RrcObservation.operator.in_(filters.op))
            if filters.svc:
                base_q = base_q.filter(RrcObservation.service.in_(filters.svc))
            if filters.band:
                base_q = base_q.filter(RrcObservation.band.in_(filters.band))
            if filters.dep:
                base_q = base_q.filter(RrcObservation.dep.in_(filters.dep))
            # tech is implicit (comes from the message's techno)

        n = base_q.count()
        if p.spec_kind == "numeric":
            distinct = (
                base_q.with_entities(RrcObservation.raw_num).distinct().count()
            )
        else:
            distinct = (
                base_q.with_entities(RrcObservation.raw_str).distinct().count()
            )
        rule = db.get(ConversionRule, p.param_id)
        dominant = _dominant(db, project.id, p, rule)
        summaries.append(
            ParamSummary(
                param_id=p.param_id,
                leaf=p.leaf,
                path=p.path,
                n=n,
                distinct=distinct,
                dominant=dominant,
            )
        )
    return ParamList(params=summaries)


def _bins_for_numeric(low: float, high: float, bin_width: float, rule: ConversionRule | None) -> tuple[list[str], list[float], float]:
    """Return bin labels (converted), bin centers (raw), and bin_width."""
    bins_centers = []
    cur = low
    while cur <= high:
        bins_centers.append(cur)
        cur += bin_width
    if rule:
        labels = [f"{(c * rule.scale + rule.offset):.{rule.decimals}f} {rule.unit}".replace(".", ",") for c in bins_centers]
    else:
        labels = [f"{c:.0f}" for c in bins_centers]
    return labels, bins_centers, bin_width


def build_param_detail(
    db: Session,
    project: Project,
    param_id: str,
    group_by: str,
    filters: FilterContext | None = None,
) -> ParamDetail:
    param = db.get(DictParam, param_id)
    if not param:
        raise LookupError("param not found")
    if param.simulate_error:
        # Honour the mock's simulated upstream errors
        raise RuntimeError("UPSTREAM_ERROR")

    rule = db.get(ConversionRule, param_id)
    msg = db.get(DictMessage, param.msg_id)
    rule_schema = (
        ConversionRuleSchema(
            formula=rule.formula,
            scale=rule.scale,
            offset=rule.offset,
            unit=rule.unit,
            decimals=rule.decimals,
            ref=rule.ref,
        )
        if rule
        else None
    )

    q = db.query(RrcObservation).filter(
        RrcObservation.project_id == project.id,
        RrcObservation.param_id == param_id,
    )
    if filters:
        if filters.op:
            q = q.filter(RrcObservation.operator.in_(filters.op))
        if filters.svc:
            q = q.filter(RrcObservation.service.in_(filters.svc))
        if filters.band:
            q = q.filter(RrcObservation.band.in_(filters.band))
        if filters.dep:
            q = q.filter(RrcObservation.dep.in_(filters.dep))
    obs = q.all()

    # histogram + matrix
    histogram: list[HistogramBin] = []
    matrix_bins_labels: list[str] = []
    matrix_rows: list[MatrixRow] = []

    if param.spec_kind == "numeric":
        low, high = param.spec["range"]
        bin_width = param.spec["bin_width"]
        labels, centers, bw = _bins_for_numeric(low, high, bin_width, rule)
        counts = [0] * len(labels)
        # Group by index
        for o in obs:
            if o.raw_num is None:
                continue
            idx = min(len(labels) - 1, max(0, int((o.raw_num - low) // bw)))
            counts[idx] += 1
        for label, cen, cnt in zip(labels, centers, counts):
            vnum = (cen * rule.scale + rule.offset) if rule else cen
            histogram.append(HistogramBin(label=label, value_num=vnum, count=cnt))
        matrix_bins_labels = labels
        # rows
        key_rows: dict[str, list[int]] = defaultdict(lambda: [0] * len(labels))
        for o in obs:
            if o.raw_num is None:
                continue
            idx = min(len(labels) - 1, max(0, int((o.raw_num - low) // bw)))
            key = _group_key(o, group_by)
            key_rows[key][idx] += 1
        for key, cnts in sorted(key_rows.items()):
            total = sum(cnts)
            cells = [
                MatrixCell(bin_index=i, pct=round(c * 100 / total, 2) if total else 0.0, n=c)
                for i, c in enumerate(cnts)
                if c > 0
            ]
            matrix_rows.append(MatrixRow(key=key, total=total, cells=cells))
    else:
        values = param.spec["values"]
        matrix_bins_labels = list(values)
        counts = {v: 0 for v in values}
        for o in obs:
            if o.raw_str in counts:
                counts[o.raw_str] += 1
        for v in values:
            histogram.append(HistogramBin(label=v, value_num=None, count=counts[v]))
        key_rows: dict[str, dict[str, int]] = defaultdict(lambda: {v: 0 for v in values})
        for o in obs:
            if o.raw_str not in counts:
                continue
            key = _group_key(o, group_by)
            key_rows[key][o.raw_str] += 1
        for key, cmap in sorted(key_rows.items()):
            total = sum(cmap.values())
            cells = []
            for i, v in enumerate(values):
                c = cmap[v]
                if c > 0:
                    cells.append(MatrixCell(bin_index=i, pct=round(c * 100 / total, 2) if total else 0.0, n=c))
            matrix_rows.append(MatrixRow(key=key, total=total, cells=cells))

    dominant = _dominant(db, project.id, param, rule)
    return ParamDetail(
        fiche=ParamFiche(
            techno=msg.techno,
            message=msg.name,
            path=param.path,
            leaf=param.leaf,
            type=param.type,
            dominant=dominant,
            conversion_rule=rule_schema,
        ),
        histogram=histogram,
        matrix=ParamMatrix(bins=matrix_bins_labels, rows=matrix_rows),
    )


def _group_key(o: RrcObservation, group_by: str) -> str:
    if group_by == "operator":
        return o.operator
    if group_by == "band":
        return o.band
    return f"{o.operator} · {o.band}"


def build_param_map(
    db: Session,
    project: Project,
    param_id: str,
    filters: FilterContext | None = None,
) -> ParamMap:
    param = db.get(DictParam, param_id)
    if not param:
        raise LookupError("param not found")
    if param.simulate_error:
        raise RuntimeError("UPSTREAM_ERROR")

    rule = db.get(ConversionRule, param_id)
    q = db.query(RrcObservation).filter(
        RrcObservation.project_id == project.id,
        RrcObservation.param_id == param_id,
        RrcObservation.lat.isnot(None),
        RrcObservation.lng.isnot(None),
    )
    if filters:
        if filters.op:
            q = q.filter(RrcObservation.operator.in_(filters.op))
        if filters.svc:
            q = q.filter(RrcObservation.service.in_(filters.svc))
        if filters.band:
            q = q.filter(RrcObservation.band.in_(filters.band))
        if filters.dep:
            q = q.filter(RrcObservation.dep.in_(filters.dep))

    obs = q.order_by(RrcObservation.capture_id, RrcObservation.seq).limit(500).all()

    features: list[MapFeature] = []
    for o in obs:
        if param.spec_kind == "numeric":
            v = o.raw_num
            display = _convert_display(rule, v) if rule else f"{v}"
            features.append(
                MapFeature(
                    geometry=MapPointGeometry(coordinates=(o.lng, o.lat)),
                    properties=MapPointProperties(value=float(v) if v is not None else 0.0, display=display or ""),
                )
            )
        else:
            v = o.raw_str
            features.append(
                MapFeature(
                    geometry=MapPointGeometry(coordinates=(o.lng, o.lat)),
                    properties=MapPointProperties(value=v or "", display=v or ""),
                )
            )

    if param.spec_kind == "numeric":
        low, high = param.spec["range"]
        bw = param.spec["bin_width"]
        stops = []
        cur = low
        while cur <= high:
            lbl = _convert_display(rule, cur) if rule else f"{cur:.0f}"
            stops.append(LegendStop(value=float(cur * rule.scale + rule.offset) if rule else float(cur), label=lbl or ""))
            cur += bw
        legend = MapLegend(kind="numeric", stops=stops)
    else:
        legend = MapLegend(
            kind="categorical",
            classes=[LegendClass(value=v, label=v) for v in param.spec["values"]],
        )
    return ParamMap(features=features, legend=legend)


def _convert_display(rule: ConversionRule | None, raw: float | int | None) -> str | None:
    if rule is None or raw is None:
        return None
    v = raw * rule.scale + rule.offset
    return f"{v:.{rule.decimals}f} {rule.unit}".replace(".", ",")
