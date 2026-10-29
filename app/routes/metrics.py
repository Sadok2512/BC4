"""Capture-local measured chronograms, with replayable provenance."""
import csv
import io
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.kpi.metrics import metric_catalog
from app.kpi.population import attributed_source, context_sql, predicate, validate_operators
from app.routes.tasks import project, evidence, filters

router = APIRouter(tags=['metrics'], dependencies=[Depends(get_current_user)])
class MetricInfo(BaseModel):
    code: str
    label: str
    unit: str
    source_table: str
    source_tables: list[str]
    source_column: str
    # 0.80.1 — tech en str libre : catalog 2.50.5 inclut "Shared"/"Other"
    # (categories.yaml) en plus de LTE/NR/BOTH.
    tech: str
    kind: Literal['numeric','categorical','event']
    n_in_project: int
    decoder_version: str
    event: str
    category_label: str
    cell_scoped: bool
    cells: list[int]
    cell_options: list[dict]
    attributes: list[dict]
    # 0.80.1 — proof en str libre : catalog 2.50.5 utilise "documented-2.50"
    # (voir build_catalog.py). Pas d'enum restrictif pour permettre les
    # bumps de catalog sans toucher au schema API.
    proof: str
    available: bool
    reason: str | None = None
    alias_of: str | None = None
    event_group: str | None = None
    unproven_cells: list[dict] = []
    root_notices: list[dict] = []
    event_code: str = ""
    proof_ref: str = ""
    category: str | None = None  # 0.64.0 (F1) — champ `category` du YAML décodeur
class MetricCatalogNode(BaseModel):
    node_id: str
    parent_id: str | None = None
    order: int
    label: str
    note: str | None = None
    source: str | None = None
    # 0.80.1 — ajout "tech"/"event" pour catalog 2.50.5 (4 niveaux
    # Technology → Catégorie → Métrique → Feuilles cellule).
    node_type: Literal['tech','category','group','metric','event','leaf']
    metric_id: str | None = None
    selection: str | None = None
    event: str | None = None
    field_idx: int | None = None
    source_column: str | None = None
    unit: str = ''
    cell: str | None = None
    n: int = 0
    # 0.80.1 — proof en str libre (idem MetricInfo).
    proof: str
    selectable: bool = False
    reason: str | None = None
class CatalogReleaseInfo(BaseModel):
    """0.80.0 (Phase 3a) — ligne `catalog_release.is_current=TRUE` reflétée
    au client. `None` si la table est vide (bootstrap frais) ; dans ce cas
    la route rebascule sur l'ancien chemin legacy et `reason` l'explique."""
    version: str
    spec_version: str
    decoder_min_version: str
    sha256: str
    n_leaves: int


class MetricCatalogResponse(BaseModel):
    catalogue_version: str
    title: str
    header: str
    metrics: list[MetricInfo]
    nodes: list[MetricCatalogNode]
    # 0.80.0 — enveloppe Phase 3a (contrat front : footer "Catalog <v> ·
    # Decoder <d>" + bascule explicite release / legacy via `reason`).
    catalog_release: CatalogReleaseInfo | None = None
    decoder_version: str = ""
    reason: str = ""
class CaptureInfo(BaseModel):
    capture_id: str
    label: str
    # 0.76.1 — kind='ue'|'scanner'|null depuis nmf_capture (classifié par CONTENU).
    # Null si capture non encore décodée.
    kind: Literal['ue', 'scanner'] | None = None
class Sample(BaseModel):
    seq: int
    t_rel_s: float
    value: float | str
    tooltip: str = ''
    attributes: dict = {}
class Sampling(BaseModel):
    method: str
    factor: float
    seq_bucket_width: int | None = None
class Segment(BaseModel):
    start_s: float
    end_s: float
    value: str
class MetricSeries(BaseModel):
    cell: str = "all"
    source_table: str
    source_column: str
    code: str
    label: str
    unit: str
    kind: Literal['numeric','categorical','event']
    n_total: int
    n_returned: int
    sampling: Sampling
    states: list[str]
    segments: list[Segment]
    points: list[Sample]
class SeriesResponse(BaseModel):
    decoder_version: str
    schema_version: str
    decode_level: Literal["light","deep"]
    aggregation: str
    project_id: str
    capture_id: str
    result_id: str
    origin_seq: int
    origin_ts: str
    duration_s: float
    # 0.76.3 — meta temporelle (NFF 2.19 #START + #UT) exposée aussi côté
    # /metrics/series pour que le front puisse rendre un axe X en Clock
    # (local|UTC) sans recalcul depuis un autre endpoint. Null = capture non
    # enrichie (#START ou #UT absent) → front repli sur Capture time (s).
    nmf_start_at: str | None = None
    capture_date: str | None = None
    utc_offset_min: int | None = None
    series: list[MetricSeries]
    csv: str
    time_policy: str
class Marker(BaseModel):
    seq: int
    t_rel_s: float
    type: str
    label: str
    event_code: str | None = None
class CaptureForcing(BaseModel):
    """0.62.0 — Exposition capture-level du forçage techno/bande.

    Détecté à partir des événements NMF ``LOCK`` présents dans la
    capture. Le payload (bande / PCI / HO forcing) n'est accessible
    qu'après re-décodage Deep en 1.1.0 (phase P3) ; pour l'instant,
    on expose uniquement la **présence** et le compte."""
    active: bool
    lock_count: int = 0
    first_seq: int | None = None
    first_t_rel_s: float | None = None
    note: str = (
        "LOCK présent — forçage techno/bande actif dans la capture. "
        "Payload détaillé (bande, PCI, HO forcing) disponible après "
        "re-décodage Deep en nmf_decoder 1.1.0 (P3)."
    )
class EventsResponse(BaseModel):
    project_id: str
    capture_id: str
    result_id: str
    markers: list[Marker]
    capture_forcing: CaptureForcing | None = None

class MetricAggregateRow(BaseModel):
    """Un bucket d'agrégation metric par groupe (operator / band / …).
    0.64.0 (F1) — ``n`` entier, ``p10/p50/p90`` floats ou null si pas
    assez de points. Mêmes règles qu'un KPI agrégé."""
    operator: str | None = None
    band: str | None = None
    n: int
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None


class MetricAggregateResponse(BaseModel):
    """0.64.0 (F1) — agrégats d'une métrique Nemo (observations brutes
    décodées) par groupe. Reprend les règles d'attribution opérateur/
    bande utilisées par les KPI ``nmf_metric`` : ``app.kpi.nmf.stats``."""
    model_config = {"extra": "allow"}
    project_id: str
    metric_code: str
    group_by: str
    unit: str | None
    tech: Literal['LTE', 'NR', 'BOTH']
    kind: Literal['numeric', 'categorical']
    n: int
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    groups: list[MetricAggregateRow] = []


_METRIC_GROUP_BYS: tuple[tuple[str, ...], ...] = (
    (),
    ("operator",),
    ("band",),
    ("operator", "band"),
)


def _group_cols(group_by: str) -> tuple[str, ...]:
    key = group_by or "none"
    mapping = {
        "none":          (),
        "operator":      ("operator",),
        "band":          ("band",),
        "operator_band": ("operator", "band"),
    }
    if key not in mapping:
        raise HTTPException(422, dict(reason='unknown_group_by', allowed=list(mapping)))
    return mapping[key]


@router.get(
    '/projects/{project_id}/metrics/{code}/aggregate',
    response_model=MetricAggregateResponse,
)
def metric_aggregate(
    project_id: str,
    code: str,
    group_by: Literal['none', 'operator', 'band', 'operator_band'] = 'none',
    f: dict = Depends(filters),
    db: Session = Depends(get_db),
):
    """Agrégats n / p10 / p50 / p90 d'une métrique Nemo par groupe.

    0.64.0 (F1) — permet au front, dans l'onglet Métriques, d'afficher
    un histogramme par opérateur / bande sans exposer de nouveau code
    côté client. Reuse strict de ``app.kpi.nmf.stats`` : même attribution
    opérateur/bande que les KPI ``nmf_metric``, mêmes filtres contexte,
    mêmes règles de percentile (sur les observations, jamais sur des
    moyennes de groupes).

    ``code`` doit être présent dans ``metric_catalog(db)`` ; sinon 422.
    """
    project(db, project_id)
    validate_operators(db, project_id, f)
    definitions = metric_catalog(db)
    if code not in definitions:
        raise HTTPException(422, dict(reason='unknown_metric', code=code))
    metric = definitions[code]
    if metric.kind == 'categorical':
        raise HTTPException(422, dict(reason='categorical_metric_not_aggregated', code=code))
    group_cols = _group_cols(group_by)

    from app.kpi.nmf import stats
    operators_filter = f.get('operator') or []
    # 0.64.1 — on passe metric.sql (qui applique /1e6 pour les bit/s →
    # Mbit/s) plutôt que source_sql(code) raw ; sinon un KPI débit
    # renvoie des valeurs 1e6× trop grandes (bug 0.64.0).
    total, groups = stats(
        db, project_id, code, list(group_cols), operators_filter,
        filters=f, sql_override=metric.sql,
    )

    def _row(row: dict) -> dict:
        return {
            'operator': row.get('operator'),
            'band':     row.get('band'),
            'n':        int(row.get('n') or 0),
            'p10':      row.get('p10'),
            'p50':      row.get('p50'),
            'p90':      row.get('p90'),
        }

    return dict(
        project_id   = project_id,
        metric_code  = code,
        group_by     = group_by,
        unit         = metric.unit,
        tech         = metric.tech,
        kind         = metric.kind,
        n            = int(total.get('n') or 0),
        p10          = total.get('p10'),
        p50          = total.get('p50'),
        p90          = total.get('p90'),
        groups       = [_row(r) for r in groups],
    )


@router.get('/projects/{project_id}/metrics', response_model=MetricCatalogResponse)
def catalog(project_id: str, db: Session=Depends(get_db)):
    """0.80.0 (Phase 3a) — contrat Phase 3a :
    si `catalog_release.is_current` est posé → chemin **v4** (lit
    `catalog_<v>.json`, servit 5115 feuilles affichées, enveloppe
    `catalog_release` + `decoder_version` + `reason='from_catalog_release'`).
    Sinon → fallback legacy BC2 (`catalog_v3`+`catalogue_v6`) avec
    `reason='fallback_legacy_no_catalog_release'`, enveloppe `catalog_release`
    forcée à `None` — jamais de default silencieux."""
    project(db,project_id)
    from app.kpi.catalog_release.registry import current_catalog
    cur = current_catalog(db)
    stamp=db.execute(text("""SELECT md5(coalesce(string_agg(
      capture_id || ':' || decoder_version || ':' || coalesce(decoded_at::text,''),
      ',' ORDER BY capture_id),'')) FROM nmf_capture WHERE project_id=:pid"""),
      {'pid':project_id}).scalar_one()
    # Clé de cache inclut la version catalog_release pour qu'un bump
    # catalog invalide automatiquement sans TRUNCATE manuel.
    cache_stamp = f"{stamp}|cat={cur.version if cur else 'legacy'}"
    cached=db.execute(text("""SELECT payload FROM metrics_catalog_cache
      WHERE project_id=:pid AND decode_stamp=:stamp"""),
      {'pid':project_id,'stamp':cache_stamp}).scalar_one_or_none()
    if cached is not None:return cached
    if cur:
        from app.kpi.metrics_catalog_v4 import build_catalog_v4
        payload = build_catalog_v4(db, project_id, cur)
    else:
        from app.kpi.metrics_v3 import catalog as catalog_v3
        from app.kpi.metrics_catalogue_v6 import catalogue as catalogue_v6
        from app.nmf_decoder import DECODER_VERSION
        metric_rows=catalog_v3(db,project_id)
        payload=dict(catalogue_v6(db,project_id,metric_rows),metrics=metric_rows)
        payload['catalog_release'] = None
        payload['decoder_version'] = DECODER_VERSION
        payload['reason'] = 'fallback_legacy_no_catalog_release'
    db.execute(text("""INSERT INTO metrics_catalog_cache(project_id,decode_stamp,payload)
      VALUES(:pid,:stamp,CAST(:payload AS jsonb)) ON CONFLICT(project_id) DO UPDATE SET
      decode_stamp=excluded.decode_stamp,payload=excluded.payload,updated_at=now()"""),
      {'pid':project_id,'stamp':cache_stamp,'payload':json.dumps(payload)})
    db.commit()
    return payload

@router.get('/projects/{project_id}/metrics/captures', response_model=list[CaptureInfo])
def captures(project_id: str,f: dict=Depends(filters),db: Session=Depends(get_db)):
    project(db,project_id)
    validate_operators(db,project_id,f)
    clauses=['m.project_id=:pid','m.capture_id IS NOT NULL'];p={'pid':project_id}
    if f.get('operator_mode')=='none':clauses.append('FALSE')
    for key in ('operator','band','rat','tech','service_type','phase','env','dep'):
        if f.get(key):
            clauses.append(f'(m.{key}=ANY(:{key})'+(' OR m.operator IS NULL' if key=='operator' and 'N/D' in f[key] else '')+')');p[key]=f[key]
    geo=[]
    for key,col in {'dor':'dor','dr':'dr','plaque':'plaque','arcep':'arcep_zone','commune':'commune','insee':'insee'}.items():
        if f.get(key):geo.append(f'c.{col}=ANY(:{key})');p[key]=f[key]
    if geo:clauses.append("m.ecgi_source='sib1_strict_capture_earfcn' AND EXISTS (SELECT 1 FROM cell_ref c WHERE c.eci=m.ecgi AND "+' AND '.join(geo)+')')
    rows=db.execute(text('SELECT DISTINCT m.capture_id FROM measurement_points m WHERE '+' AND '.join(clauses)+' ORDER BY m.capture_id'),p)
    caps_from_measurements=[r[0] for r in rows]
    # 0.76.2 — expose AUSSI les captures scanner (kind='scanner') qui n'ont jamais
    # de measurement_points par design. L'utilisateur peut les sélectionner et
    # voir le banner "Scanner capture" + leaves UE grayed.
    scanner_rows=db.execute(text(
        'SELECT capture_id FROM nmf_capture WHERE project_id=:pid AND kind=:kind ORDER BY capture_id'
    ),{'pid':project_id,'kind':'scanner'})
    scanner_caps=[r[0] for r in scanner_rows]
    # Union ordonnée : UE captures (measurement_points) + scanner (dédoublonné).
    caps=caps_from_measurements+[c for c in scanner_caps if c not in caps_from_measurements]
    if not caps: return []
    meta={r['capture_id']:dict(r) for r in db.execute(text(
        '''SELECT c.capture_id, c.kind, n.filename
           FROM nmf_capture c JOIN nmf_file n ON n.id=c.nmf_file_id
           WHERE c.project_id=:pid AND c.capture_id=ANY(:caps)'''
    ),{'pid':project_id,'caps':caps}).mappings()}
    return [dict(capture_id=c,label=meta.get(c,{}).get('filename',c),kind=meta.get(c,{}).get('kind')) for c in caps]

TIME_SQL = '''SELECT seq,ts FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
 UNION SELECT seq,ts FROM stg_event WHERE project_id=:pid AND capture_id=:cap ORDER BY seq'''
def clock(db,pid,cap):
    from app.signaling.capture_cache import shared_clock
    def build():
        rows=db.execute(text(TIME_SQL),{'pid':pid,'cap':cap}).mappings().all()
        if not rows:raise HTTPException(404,'capture_not_found_in_project')
        times={};origin=None;origin_seq=None;origin_ts=None;previous=None
        for r in rows:
            try:
                h,m,s=r['ts'].split(':');seconds=Decimal(h)*3600+Decimal(m)*60+Decimal(s)
            except (AttributeError,ValueError,InvalidOperation):continue
            if origin is None:origin=seconds;origin_seq=r['seq'];origin_ts=r['ts']
            if previous is not None and seconds<previous:
                raise HTTPException(409,dict(reason='capture_timestamp_regression',capture_id=cap,seq=r['seq'],ts=r['ts']))
            if r['seq'] in times and times[r['seq']] != float(seconds-origin):
                raise HTTPException(409,'conflicting_timestamp_at_seq')
            times[r['seq']]=float(seconds-origin);previous=seconds
        if not times:raise HTTPException(409,'capture_has_no_valid_timestamp')
        return times,origin_seq,origin_ts
    return shared_clock(db,pid,cap,build)

def sample(points,limit,kind):
    """Numeric min/max over fixed-width seq buckets; ties resolved by seq.
    Categorical transitions are lossless: exceeding the cap is explicit (422).
    """
    n=len(points)
    if kind=='categorical':
        states=[]
        for p in points:
            if not states or p['value']!=states[-1]['value']:states.append(p)
        if len(states)>limit:raise HTTPException(422,dict(reason='categorical_transitions_exceed_max_points',required=len(states),max_points=limit))
        return states,dict(method='state_changes',factor=n/len(states) if states else 1,seq_bucket_width=None)
    if n<=limit:return points,dict(method='none',factor=1,seq_bucket_width=None)
    width=max(1,math.ceil((points[-1]['seq']-points[0]['seq']+1)/(limit//2)))
    buckets={}
    for p in points:buckets.setdefault((p['seq']-points[0]['seq'])//width,[]).append(p)
    selected={}
    for rows in buckets.values():
        for p in (min(rows,key=lambda r:(r['value'],r['seq'])),max(rows,key=lambda r:(r['value'],-r['seq']))):selected[p['seq']]=p
    out=sorted(selected.values(),key=lambda r:r['seq'])
    return out,dict(method='seq_bucket_min_max',factor=n/len(out),seq_bucket_width=width)

@router.get('/projects/{project_id}/metrics/series', response_model=SeriesResponse)
def series(project_id: str,capture_id: str,codes: str,cell: str|None=None,attr: str|None=None,from_seq: int|None=Query(None,ge=0),to_seq: int|None=Query(None,ge=0),max_points: int=Query(5000,ge=2,le=100000),f: dict=Depends(filters),db: Session=Depends(get_db)):
    from app.kpi.metrics_v3 import definitions,parse_selection,Dataset,DERIVED
    if cell is not None or attr is not None or any(c in DERIVED or c.startswith('evt_') or c.startswith('cap_') or '@' in c or '~' in c for c in codes.split(',')):
        project(db,project_id)
        if from_seq is not None and to_seq is not None and from_seq>to_seq:raise HTTPException(422,'from_seq_after_to_seq')
        ds=Dataset(db,project_id,capture_id,f,from_seq,to_seq)
        selected=[parse_selection(c,definitions(),cell or 'all',attr) for c in dict.fromkeys(codes.split(','))]
        if len(selected)>64:raise HTTPException(422,'too_many_metrics')
        return ds.response(selected,max_points)
    project(db,project_id)
    validate_operators(db,project_id,f)
    definitions=metric_catalog(db)
    selected=list(dict.fromkeys(codes.split(',')))
    def reject_metric():
        allowed=sorted(m['code'] for m in catalog(project_id,db))
        raise HTTPException(422,dict(reason='unknown_metric',allowed=allowed))
    if any(c not in definitions for c in selected):reject_metric()
    if from_seq is not None and to_seq is not None and from_seq>to_seq:raise HTTPException(422,'from_seq_after_to_seq')
    times,origin_seq,origin_ts=clock(db,project_id,capture_id)
    params={'pid':project_id,'cap':capture_id,'ctx_cap':capture_id,'lo':from_seq,'hi':to_seq}
    sqls=[];results=[];all_values={}
    state=db.execute(text('SELECT decoder_version,schema_version,decode_level FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap'),params).mappings().first()
    if state is None:raise HTTPException(409,'capture_requires_decode')
    condition,fp=predicate(f);params.update(fp)
    if condition!='TRUE':
        filter_sql='SELECT seq FROM ('+context_sql()+') c WHERE '+condition
        params['allowed_seq']=[r[0] for r in db.execute(text(filter_sql),params)]
        sqls.append(filter_sql)
        if state['decode_level']=='light':
            bucket_sql="""SELECT l.seq FROM nmf_event_light l WHERE l.project_id=:pid AND l.capture_id=:cap
              AND l.seq=ANY(:allowed_seq) AND NOT EXISTS(SELECT 1 FROM stg_event_raw r
                WHERE r.project_id=l.project_id AND r.capture_id=l.capture_id AND r.event_code=l.event_code
                AND r.seq BETWEEN l.seq AND l.seq_last AND NOT(r.seq=ANY(:allowed_seq)))"""
            params['admissible_buckets']=[r[0] for r in db.execute(text(bucket_sql),params)]
            sqls.append(bucket_sql)
    for code in selected:
        m=definitions[code]
        sql='SELECT seq,value FROM ('+m.sql+') source WHERE capture_id=:cap AND (CAST(:lo AS integer) IS NULL OR seq>=:lo) AND (CAST(:hi AS integer) IS NULL OR seq<=:hi) ORDER BY seq'
        if condition!='TRUE':
            key='admissible_buckets' if state['decode_level']=='light' else 'allowed_seq'
            sql=sql.replace(' ORDER BY seq',' AND seq=ANY(:'+key+') ORDER BY seq')
        sqls.append(sql)
        rows=db.execute(text(sql),params).mappings().all()
        # A valid capture may have no observations of a project metric. Only
        # check project availability in that case, without recounting all fields.
        if not rows and not db.execute(text('SELECT EXISTS(SELECT 1 FROM ('+m.sql+') available LIMIT 1)'),{'pid':project_id}).scalar_one():
            reject_metric()
        if any(r['seq'] not in times for r in rows):raise HTTPException(409,dict(reason='metric_timestamp_missing',code=code))
        points=[dict(seq=r['seq'],t_rel_s=times[r['seq']],value=str(r['value']) if m.kind=='categorical' else float(r['value'])) for r in rows]
        for p in points:all_values.setdefault(p['seq'],{})[code]=p['value']
        out,sampling=sample(points,max_points,m.kind)
        segments=[dict(start_s=p['t_rel_s'],end_s=out[i+1]['t_rel_s'] if i+1<len(out) else points[-1]['t_rel_s'],value=p['value']) for i,p in enumerate(out)] if m.kind=='categorical' else []
        results.append(dict(segments=segments,code=code,label=m.label,unit=m.unit,kind=m.kind,n_total=len(points),n_returned=len(out),sampling=sampling,states=list(dict.fromkeys(p['value'] for p in points)) if m.kind=='categorical' else [],points=out))
    for result in results:
        for p in result['points']:
            p['tooltip']='seq '+str(p['seq'])+' · '+str(p['t_rel_s'])+' s\n'+'\n'.join(definitions[c].label+': '+str(all_values[p['seq']].get(c,'N/D'))+' '+definitions[c].unit for c in selected)
    rid=evidence(db,project_id,';\n'.join([TIME_SQL,*sqls]),{**params,'applied_filters':f,'codes':selected,'max_points':max_points},{'series':[{k:r[k] for k in ('code','n_total','n_returned','sampling')} for r in results]})
    output=io.StringIO();writer=csv.writer(output);writer.writerow(['result_id','capture_id','code','unit','seq','t_rel_s','value'])
    for r in results:
        for p in r['points']:writer.writerow([rid,capture_id,r['code'],r['unit'],p['seq'],p['t_rel_s'],p['value']])
    for result in results:
        metric=definitions[result['code']]
        result.update(source_table='nmf_event_light' if state['decode_level']=='light' else metric.source_table,source_column=metric.source_column)
    # 0.76.3 — meta temporelle du fichier source joint via nmf_capture.
    file_meta = db.execute(text(
        'SELECT f.start_at AS start_at, f.utc_offset_min AS utc_offset_min '
        'FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id '
        'WHERE c.project_id=:pid AND c.capture_id=:cap'
    ),{'pid':project_id,'cap':capture_id}).mappings().first() or {'start_at':None,'utc_offset_min':None}
    from app.kpi.service import date_from_start_at_py
    return dict(**state,aggregation='schema per capture-second' if state['decode_level']=='light' else 'none',project_id=project_id,capture_id=capture_id,result_id=rid,origin_seq=origin_seq,origin_ts=origin_ts,nmf_start_at=file_meta['start_at'],capture_date=date_from_start_at_py(file_meta['start_at']),utc_offset_min=file_meta['utc_offset_min'],duration_s=max(times.values()),series=results,csv=output.getvalue(),time_policy='ts - premier ts valide en ordre seq ; égalités conservées ; régression rejetée ; aucune interpolation')

EVENT_SQL = '''SELECT e.seq,e.message, EXISTS(SELECT 1 FROM param_occurrence p WHERE p.project_id=:pid AND p.stg_event_id=e.id AND p.path LIKE '%mobilityControlInfo%') mobility
 FROM stg_event e WHERE e.project_id=:pid AND e.capture_id=:cap AND e.message IN
 ('RRCConnectionReconfiguration','RRCConnectionReestablishmentRequest','RRCConnectionSetup','RRCConnectionRelease','RRCSetup','RRCRelease') ORDER BY e.seq'''
TASK_SQL = 'SELECT seq_daa,seq_dcomp,task_type FROM task_run WHERE project_id=:pid AND capture_id=:cap ORDER BY seq_start'

# 0.62.0 — Mapping événements NMF 1.1.0 (schemas-pending) vers les types
# de markers exposés par /captures/{cid}/events. Les clés sont les
# ``event_code`` tels qu'ils apparaissent dans ``stg_event_raw.event_code``.
# Les types sont les buckets sémantiques demandés par la mission :
# attach · detach · bearer · reselection · meas_event · roam · lock ·
# mark · channel · audio · voip · ho_info · rach · l3sm · rrc_lte ·
# call. ``rrc`` reste réservé aux messages RRC décodés ASN.1 (via
# ``stg_event``).
_RAW_EVENT_TYPE: dict[str, tuple[str, str]] = {
    # RRC-level LTE events (différents des messages ASN.1 déjà exposés via `rrc`)
    'RRA':  ('rrc_lte', 'RRC Attach request (LTE)'),
    'RRC':  ('rrc_lte', 'RRC Attach complete (LTE)'),
    'RRD':  ('rrc_lte', 'RRC Detach (LTE)'),
    # Attach / detach GPRS/EPS
    'GAA':  ('attach',  'GPRS/EPS attach attempt'),
    'GAC':  ('attach',  'GPRS/EPS attach complete'),
    'GAD':  ('detach',  'GPRS/EPS detach'),
    # Bearer / PDP context
    'PBA':  ('bearer',  'PDP context activate attempt'),
    'PBC':  ('bearer',  'PDP context activate complete'),
    'PBD':  ('bearer',  'PDP context deactivate'),
    # Call events (ajoutés en bonus, hors mission mais cohérents)
    'CAA':  ('call',    'Call attempt'),
    'CAC':  ('call',    'Call complete'),
    'CAD':  ('call',    'Call disconnect'),
    'PAA':  ('call',    'Packet call attempt'),
    'PAC':  ('call',    'Packet call complete'),
    'PAD':  ('call',    'Packet call disconnect'),
    # Reselection / handover
    'CREL': ('reselection', 'Cell reselection'),
    'HOI':  ('ho_info', 'Handover info'),
    'HOA':  ('ho_info', 'Handover attempt'),
    'HOS':  ('ho_info', 'Handover success'),
    # Measurement events
    'MEI':  ('meas_event',    'Measurement event'),
    'NLIST':('meas_event',    'Neighbour list'),
    'SEI':  ('meas_event',    'Serving cell event'),
    # Divers
    'ROAM': ('roam',    'Roaming event'),
    'LOCK': ('lock',    'Lock/forcing event'),
    'MARK': ('mark',    'User mark'),
    'PCHI': ('channel', 'Channel info'),
    'RACHI':('rach',    'RACH info'),
    'AQRX': ('audio',   'Audio quality RX'),
    'AQI':  ('audio',   'Audio quality info'),
    'VOIPI':('voip',    'VoIP event'),
    'L3SM': ('l3sm',    'L3 state machine'),
}
_RAW_TYPES_ALLOWED: set[str] = {t for t, _l in _RAW_EVENT_TYPE.values()}
_EVENTS_TYPES_ALLOWED: set[str] = {'task', 'ho', 'rlf', 'rrc'} | _RAW_TYPES_ALLOWED

RAW_EVENT_SQL = '''SELECT seq, event_code FROM stg_event_raw
 WHERE project_id=:pid AND capture_id=:cap AND event_code = ANY(:raw_codes)
 ORDER BY seq'''
LOCK_SQL = '''SELECT seq FROM stg_event_raw
 WHERE project_id=:pid AND capture_id=:cap AND event_code='LOCK'
 ORDER BY seq'''

@router.get('/projects/{project_id}/captures/{capture_id}/events',response_model=EventsResponse)
def events(project_id: str,capture_id: str,types: str='task,ho,rlf,rrc',f: dict=Depends(filters),db: Session=Depends(get_db)):
    project(db,project_id);validate_operators(db,project_id,f);wanted=set(types.split(','))
    if not wanted<=_EVENTS_TYPES_ALLOWED:
        raise HTTPException(422,dict(reason='unknown_marker_type',allowed=sorted(_EVENTS_TYPES_ALLOWED)))
    times,_,_=clock(db,project_id,capture_id);params={'pid':project_id,'cap':capture_id};markers=[]
    condition,fp=predicate(f);params.update(fp);params['ctx_cap']=capture_id
    filter_sql='SELECT seq FROM ('+context_sql()+') c WHERE '+condition
    allowed=None if condition=='TRUE' else {r[0] for r in db.execute(text(filter_sql),params)}
    def add(seq,kind,label,event_code=None):
        if seq is None or (allowed is not None and seq not in allowed):return
        if seq not in times:raise HTTPException(409,dict(reason='event_timestamp_missing',seq=seq))
        markers.append(dict(seq=seq,t_rel_s=times[seq],type=kind,label=label,event_code=event_code))
    if 'task' in wanted:
        for r in db.execute(text(TASK_SQL),params).mappings():
            for key,label in [('seq_daa','DAA'),('seq_dcomp','DCOMP')]:add(r[key],'task',label+' · '+r['task_type'])
    if wanted & {'ho','rlf','rrc'}:
        for r in db.execute(text(EVENT_SQL),params).mappings():
            name=r['message'];kind='ho' if name=='RRCConnectionReconfiguration' and r['mobility'] else 'rlf' if name=='RRCConnectionReestablishmentRequest' else 'rrc' if name in ('RRCConnectionSetup','RRCConnectionRelease','RRCSetup','RRCRelease') else None
            if kind in wanted:add(r['seq'],kind,name)
    # 0.62.0 — markers depuis stg_event_raw pour les 23 event_codes
    # 1.1.0 (RRA, RRC_LTE, PBA, LOCK, MARK, …). On restreint les codes
    # SQL à ceux dont le type est dans `wanted` pour éviter un scan
    # inutile.
    wanted_raw_codes = [c for c, (t, _l) in _RAW_EVENT_TYPE.items() if t in wanted]
    if wanted_raw_codes:
        params['raw_codes'] = wanted_raw_codes
        for r in db.execute(text(RAW_EVENT_SQL), params).mappings():
            kind, label = _RAW_EVENT_TYPE[r['event_code']]
            add(r['seq'], kind, label, event_code=r['event_code'])
    markers.sort(key=lambda r:(r['seq'],r['type'],r['label']))
    # 0.62.0 — capture.forcing (toujours calculé, pas filtré par `types`)
    lock_rows = db.execute(text(LOCK_SQL), {'pid': project_id, 'cap': capture_id}).mappings().all()
    forcing = None
    if lock_rows:
        first = lock_rows[0]
        forcing = dict(
            active=True,
            lock_count=len(lock_rows),
            first_seq=first['seq'],
            first_t_rel_s=times.get(first['seq']),
        )
    else:
        forcing = dict(active=False, lock_count=0)
    rid=evidence(db,project_id,';\n'.join([TIME_SQL,TASK_SQL,EVENT_SQL,RAW_EVENT_SQL,LOCK_SQL,filter_sql]),{**params,'applied_filters':f,'types':sorted(wanted)},{'markers':len(markers),'lock':forcing.get('lock_count',0)})
    return dict(project_id=project_id,capture_id=capture_id,result_id=rid,markers=markers,capture_forcing=forcing)
