"""Typed table/analysis contract for the Metrics v3 workspace."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project,filters
from app.routes.metrics import MetricSeries
from app.kpi.metrics_v3 import Dataset,definitions,parse_selection
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
class MapPoint(BaseModel):
    seq:int;lat:float;lng:float;code:str;value:float|str;t_rel_s:float|None;tooltip:str
    serving_cell_id:str|None=None;serving_cell_seq:int|None=None
    serving_cell_ref_id:str|None=None;serving_site_id:str|None=None;serving_site_name:str|None=None
    serving_cell_lat:float|None=None;serving_cell_lng:float|None=None
    serving_cell_source:Literal['chi_previous_seq_cell_ref_exact']|None=None
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
    histogram:list[Histogram];scatter:list[Scatter];map_points:list[MapPoint]
    connected_seconds:float|None;connected_reason:str|None;pair_rates:list[PairRate];gaps:list[str];csv:str
@router.get('/projects/{project_id}/metrics/table',response_model=Analysis)
@router.get('/projects/{project_id}/metrics/analysis',response_model=Analysis)
def analysis(project_id:str,capture_id:str,codes:str,cell:str='all',attr:str|None=None,
             x:str|None=None,include_map:bool=False,group_by:Literal['none','operator','band','operator_band']='operator',
             from_seq:int|None=Query(None,ge=0),to_seq:int|None=Query(None,ge=0),max_points:int=Query(5000,ge=2,le=100000),
             page:int=Query(1,ge=1),page_size:int=Query(1000,ge=25,le=5000),
             table_only:bool=False,cell_pci:int|None=Query(None,ge=0),
             cell_arfcn:int|None=Query(None,ge=0),
             f:dict=Depends(filters),db:Session=Depends(get_db)):
    project(db,project_id)
    if from_seq is not None and to_seq is not None and from_seq>to_seq:raise HTTPException(422,'from_seq_after_to_seq')
    tokens=list(dict.fromkeys(codes.split(',')))
    if len(tokens)>64:raise HTTPException(422,'too_many_metrics')
    selected=[parse_selection(c,definitions(),cell,attr) for c in tokens]
    lean_table=(
        table_only and len(selected)==1
        and bool(selected[0].get('cell_type_filter'))
        and selected[0].get('event')=='CELLMEAS'
    )
    return Dataset(db,project_id,capture_id,f,from_seq,to_seq,lean_table=lean_table).response(
        selected,max_points,group_by,x,include_map,page,page_size,table_only,
        cell_pci,cell_arfcn,
    )
