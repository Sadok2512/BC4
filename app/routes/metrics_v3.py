"""Typed table/analysis contract for the Metrics v3 workspace."""
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project,filters
from app.routes.metrics import MetricSeries
from app.kpi.metrics_v3 import Dataset,definitions,parse_selection
from app.kpi.service import date_from_start_at_py
from app.kpi.metrics_map import build_map_points,load_gps_fixes_scoped
from app.schemas.metric_map import MetricMapPoint
router=APIRouter(tags=['metrics'],dependencies=[Depends(get_current_user)])
Scalar=float|str|None
class Column(BaseModel):
    code:str;label:str;unit:str;kind:Literal['numeric','categorical','event'];cell:str
    cell_label:str|None=None;cell_system:Literal['LTE','NR']|None=None
    cell_internal_index:int|None=None
class TableRow(BaseModel):
    second:int;t_rel_s:float;seq_first:int;seq_last:int;time_label:str
    # 0.75.0 — temps absolu + GPS par ligne (previous-or-same seq, jamais interpolé).
    time_local:str|None=None;time_utc:str|None=None
    lat:float|None=None;lon:float|None=None
    gps_source:Literal['exact','previous_fix']|None=None
    gps_age_s:float|None=None
    cell_label:str|None=None;cell_system:Literal['LTE','NR']|None=None
    cell_pci:float|None=None;cell_arfcn:float|None=None
    cell_internal_index:int|None=None
    reason:str|None=None
    values:dict[str,Scalar];counts:dict[str,int]
    # 0.82.2 — colonne Task : CMDREQ → CMDCOMP par (capture_id, seq ≤).
    # task_name = action (StartHTTPTransfer, Wait, StartScript, …), task_index
    # = cmd_index si présent dans CMDREQ, null hors tâche. Jamais inventé.
    task_name:str|None=None;task_index:int|None=None
class Distribution(BaseModel):
    value:float|str;n:int
class Histogram(BaseModel):
    code:str;label:str;operator:str|None;band:str|None;cell:str;n:int
    p10:float|None;p50:float|None;p90:float|None
    distribution:list[Distribution];per_connected_hour:float|None
class Scatter(BaseModel):
    code:str;seq:int;x_seq:int;seq_gap:int;cell:str;x:float|str;value:float|str
class PairRate(BaseModel):
    type:str;attempts:int;completed:int;success:int;known_outcomes:int;success_pct:float|None
class Analysis(BaseModel):
    project_id:str;capture_id:str;result_id:str;decoder_version:str;schema_version:str
    decode_level:Literal['deep','light'];origin_seq:int;origin_ts:str;duration_s:float
    # 0.75.0 — meta temporelle fichier source (NFF 2.19 #START + #UT).
    nmf_start_at:str|None=None    # verbatim "DD.MM.YYYY HH:MM:SS.mmm"
    capture_date:str|None=None    # dérivé YYYY-MM-DD (null si start_at absent)
    utc_offset_min:int|None=None  # #UT col 1, signe local-UTC (null si absent)
    aggregation:str;time_policy:str;pairing:str
    columns:list[Column];rows:list[TableRow];series:list[MetricSeries]
    page:int;page_size:int;total_rows:int;total_pages:int
    histogram:list[Histogram];scatter:list[Scatter];map_points:list[MetricMapPoint]
    connected_seconds:float|None;connected_reason:str|None;pair_rates:list[PairRate];gaps:list[str];csv:str

class MetricMapResponse(BaseModel):
    project_id:str;capture_id:str;result_id:str;decoder_version:str
    origin_seq:int;origin_ts:str
    nmf_start_at:str|None=None;capture_date:str|None=None
    utc_offset_min:int|None=None
    total_points:int;map_points:list[MetricMapPoint]


def _intrinsic_metric_rat(metric: dict) -> str | None:
    """Return a RAT only when the selected leaf proves it structurally.

    Semantic CELLMEAS leaves carry their radio system in ``cell_display``.
    Applying the generic context predicate to those rows is both redundant
    and lossy: a sequence with several measurement populations has a NULL
    aggregate context RAT even though the selected leaf itself is proven LTE
    or NR.
    """
    system=(metric.get('cell_display') or {}).get('system')
    return system if system in {'LTE','NR'} else None


def _apply_intrinsic_rat(selected: list[dict], f: dict) -> tuple[list[dict],dict]:
    """Push a RAT selection into semantic leaves without a context scan.

    Query parameters are a union (SQL ``ANY``/``IN``), never an intersection.
    The rewrite is deliberately limited to leaves whose RAT is explicit in
    the decoder/catalogue contract.  Mixed or untyped leaves keep the generic
    context path unchanged.
    """
    rats=f.get('rat') or []
    if not rats or not selected or not set(rats).issubset({'LTE','NR'}):
        return selected,f
    intrinsic=[_intrinsic_metric_rat(metric) for metric in selected]
    if any(rat is None for rat in intrinsic):
        return selected,f
    filtered=[metric for metric,rat in zip(selected,intrinsic) if rat in rats]
    map_filters=dict(f)
    map_filters.pop('rat',None)
    return filtered,map_filters


# Kept as a named compatibility seam for the map route and its guard tests.
_apply_intrinsic_map_rat = _apply_intrinsic_rat


def _lean_table_allowed(table_only: bool, selected: list[dict], filters: dict) -> bool:
    """Use the capture-scoped fast path for unfiltered table metrics.

    A plain metric table does not expose population context, histograms or
    event pairing. Rebuilding those full-capture structures before returning
    25 rows made ordinary CHI metrics take tens of seconds. Event contracts
    stay on the full path because their attributes may depend on pair rows.
    """
    if not table_only or not selected:
        return False
    return (
        all(not str(metric.get('base_code') or '').startswith('evt_')
            for metric in selected)
        and not any(key != 'capture_id' for key in filters)
    )


_MAP_REQUIRED_FIELDS = {
    'seq', 'lat', 'lng', 'code', 'value', 't_rel_s',
}
_MAP_OPTIONAL_BROWSER_FIELDS = {
    'serving_cell_id', 'serving_cell_seq', 'serving_cell_ref_id',
    'serving_site_id', 'serving_site_name', 'serving_cell_lat',
    'serving_cell_lng', 'serving_cell_pci', 'serving_cell_arfcn',
    'serving_cell_role',
    'serving_link_distance_m', 'serving_link_confidence',
    'serving_cell_source', 'probable_serving_cell_ref_id',
    'probable_serving_site_id', 'probable_serving_site_name',
    'probable_serving_cell_lat', 'probable_serving_cell_lng',
    'probable_serving_pci', 'probable_serving_band_mhz',
    'probable_serving_distance_m', 'neighbour_links', 'nr_anchor_link',
}


def _compact_map_point(point: dict) -> dict:
    """Drop internal and null optional fields from the browser contract.

    A 4,935-point capture used to repeat dozens of ``null`` properties plus
    the private ``_second``/position bookkeeping on every point. The compact
    form is lossless for consumers: required fields are always retained and
    every populated serving/neighbour/NR link field remains byte-for-byte.
    """
    return {
        key: value for key, value in point.items()
        if key in _MAP_REQUIRED_FIELDS
        or (key in _MAP_OPTIONAL_BROWSER_FIELDS and value is not None and value != [])
    }

@router.get('/projects/{project_id}/metrics/map',response_model=MetricMapResponse)
def metric_map(project_id:str,capture_id:str,codes:str,cell:str='all',attr:str|None=None,
               from_seq:int|None=Query(None,ge=0),to_seq:int|None=Query(None,ge=0),
               cell_pci:int|None=Query(None,ge=0),cell_arfcn:int|None=Query(None,ge=0),
               compact:bool=False,
               f:dict=Depends(filters),db:Session=Depends(get_db)):
    """Return proven map points and the capture's source-clock metadata."""
    project(db,project_id)
    if from_seq is not None and to_seq is not None and from_seq>to_seq:
        raise HTTPException(422,'from_seq_after_to_seq')
    tokens=list(dict.fromkeys(codes.split(',')))
    if len(tokens)>64:raise HTTPException(422,'too_many_metrics')
    selected=[parse_selection(code,definitions(),cell,attr) for code in tokens]
    selected,map_filters=_apply_intrinsic_rat(selected,f)
    started=time.perf_counter()
    dataset=Dataset(db,project_id,capture_id,map_filters,from_seq,to_seq,lean_series=True)
    after_init=time.perf_counter()
    if selected:
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='metrics-map-gps') as executor:
            gps_future=executor.submit(load_gps_fixes_scoped,project_id,capture_id)
            loaded=[(metric,dataset.load(
                metric,
                cell_pci=metric.get('cell_pci',cell_pci),
                cell_arfcn=metric.get('cell_arfcn',cell_arfcn),
                include_total=False,
            )) for metric in selected]
            after_load=time.perf_counter()
            gps_fixes=gps_future.result()
    else:
        loaded=[];gps_fixes=[];after_load=time.perf_counter()
    after_gps=time.perf_counter()
    points=build_map_points(dataset,loaded,gps_fixes) if loaded else []
    after_map=time.perf_counter()
    basis=':'.join((project_id,capture_id,dataset.state['decoder_version'],codes,
                    str(len(points)),str(points[0]['seq'] if points else ''),
                    str(points[-1]['seq'] if points else '')))
    server_timing=', '.join((
        f'dataset;dur={(after_init-started)*1000:.3f}',
        f'metric;dur={(after_load-after_init)*1000:.3f}',
        f'gps;dur={(after_gps-after_load)*1000:.3f}',
        f'links;dur={(after_map-after_gps)*1000:.3f}',
    ))
    response_points=[_compact_map_point(point) for point in points] if compact else points
    payload=dict(project_id=project_id,capture_id=capture_id,
                 result_id=sha256(basis.encode()).hexdigest()[:32],
                 decoder_version=dataset.state['decoder_version'],
                 origin_seq=dataset.origin_seq,origin_ts=dataset.origin_ts,
                 nmf_start_at=dataset.file_meta['start_at'],
                 capture_date=date_from_start_at_py(dataset.file_meta['start_at']),
                 utc_offset_min=dataset.file_meta['utc_offset_min'],
                 total_points=len(points),map_points=response_points)
    return ORJSONResponse(payload,headers={'Server-Timing':server_timing})

@router.get('/projects/{project_id}/metrics/table',response_model=Analysis)
@router.get('/projects/{project_id}/metrics/analysis',response_model=Analysis)
def analysis(project_id:str,response:Response,capture_id:str,codes:str,cell:str='all',attr:str|None=None,
             x:str|None=None,include_map:bool=False,group_by:Literal['none','operator','band','operator_band']='operator',
             from_seq:int|None=Query(None,ge=0),to_seq:int|None=Query(None,ge=0),max_points:int=Query(5000,ge=2,le=100000),
             page:int=Query(1,ge=1),page_size:int=Query(1000,ge=25,le=5000),
             table_only:bool=False,cell_pci:int|None=Query(None,ge=0),
             cell_arfcn:int|None=Query(None,ge=0),
             f:dict=Depends(filters),db:Session=Depends(get_db)):
    started=time.perf_counter()
    project(db,project_id)
    if from_seq is not None and to_seq is not None and from_seq>to_seq:raise HTTPException(422,'from_seq_after_to_seq')
    tokens=list(dict.fromkeys(codes.split(',')))
    if len(tokens)>64:raise HTTPException(422,'too_many_metrics')
    selected=[parse_selection(c,definitions(),cell,attr) for c in tokens]
    # A RAT filter is redundant when every selected semantic leaf proves its
    # own LTE/NR system. Removing only that proven predicate avoids rebuilding
    # the full capture context for the browser's LTE+NR table request. Other
    # predicates (operator, band, etc.) remain on the full Dataset path.
    selected,table_filters=_apply_intrinsic_rat(selected,f)
    lean_table=_lean_table_allowed(table_only,selected,table_filters)
    payload=Dataset(db,project_id,capture_id,table_filters,from_seq,to_seq,lean_table=lean_table).response(
        selected,max_points,group_by,x,include_map,page,page_size,table_only,
        cell_pci,cell_arfcn,
    )
    response.headers['Server-Timing']=f'total;dur={(time.perf_counter()-started)*1000:.3f}'
    return payload
