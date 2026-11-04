"""Signaling View contract. All observations belong to one explicit capture."""
import csv
import io
import math
import time
from typing import Literal, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project
from app.signaling import service as svc
from app.signaling import materialized as mat

router=APIRouter(prefix='/projects/{project_id}/signaling',tags=['signaling'],dependencies=[Depends(get_current_user)])

# Capture selector data is project-scoped and changes only when ingestion adds
# a file. Keep the expensive raw-event DISTINCT off the request path after the
# first load; the short TTL also guarantees eventual visibility of new files.
_CAPTURES_CACHE: dict[str, tuple[float, list[dict]]] = {}

class Line(BaseModel):
    capture_id:str
    seq:int
    t_rel_s:float|None
    protocol:Literal['RRC LTE','RRC NR','NAS','Événements Nemo','MAC-RACH']
    layer:Literal['rrc_lte','rrc_nr','nas','event','mac']
    technology:str|None
    direction:Literal['UL','DL']|None
    message_name:str
    ecgi:str|None
    pci:int|None
    size_bytes:int|None
    procedure_id:str|None
    procedure_ids:list[str]
    has_tree:bool
    source:str

class Procedure(BaseModel):
    id:str
    type:str
    technology:str|None
    seq_start:int
    seq_end:int|None
    duration_ms:float|None
    outcome:Literal['ok','fail','incomplete']
    cause:str|None
    boundary_seqs:list[int]

class Capture(BaseModel):
    capture_id:str
    label:str
    env:str|None
    # 0.76.1 — kind='ue'|'scanner'|null depuis nmf_capture.kind (classifié par
    # CONTENU, voir app/nmf_decoder/store.py:classify_capture_kind).
    kind:Literal['ue','scanner']|None=None

class Captures(BaseModel):
    project_id:str
    captures:list[Capture]

class Envelope(BaseModel):
    project_id:str
    capture_id:str
    result_id:str

class Lines(Envelope):
    rows:list[Line]
    total:int
    page:int
    size:int
    pages:int
    protocol_counts:dict[str,int]
    layer_counts:dict[str,int]
    procedures:list[Procedure]
    selected_page:int|None=None

class Bucket(BaseModel):
    t_rel_s:float
    counts:dict[str,int]
    lane_counts:dict[str,int]=Field(default_factory=dict)

class Timeline(Envelope):
    buckets:list[Bucket]
    state_events:list[dict[str,Any]]=Field(default_factory=list)
    task_events:list[dict[str,Any]]=Field(default_factory=list)
    bucket_s:float
    total:int
    missing_time:int
    t_rel_end_s:float|None=None

class Point(BaseModel):
    seq:int
    t_rel_s:float|None
    lat:float|None
    lng:float|None
    protocol:str
    layer:Literal['rrc_lte','rrc_nr','nas','event','mac']
    gps_seq:int|None
    seq_gap:int|None

class Points(Envelope):
    points:list[Point]
    markers:list[dict[str,Any]]
    positioned_count:int
    indoor:bool
    floorplan_id:str|None=None
    reason:str|None=None
    total:int|None=None
    returned:int|None=None
    truncated:bool=False

POINT_FIELDS = ['seq','t_rel_s','lat','lng','protocol_index','gps_seq','seq_gap']
MARKER_FIELDS = ['seq','t_rel_s','lat','lng','protocol_index','counts']


def compact_points_payload(project_id, capture_id, pts, total, active, f, limit):
    """Compact wire format; every map point remains reconstructible exactly."""
    protocols = list(svc.PROTOCOLS)
    protocol_index = {name: index for index, name in enumerate(protocols)}
    grouped = {}
    for point in pts:
        if point['lat'] is None or point['lng'] is None:
            continue
        key = point['gps_seq']
        if key not in grouped:
            grouped[key] = {
                'seq': point['seq'], 't_rel_s': point['t_rel_s'],
                'lat': point['lat'], 'lng': point['lng'],
                'protocol_index': protocol_index[point['protocol']],
                'counts': [0] * len(protocols),
            }
        grouped[key]['counts'][protocol_index[point['protocol']]] += 1
    point_rows = [[
        point['seq'], point['t_rel_s'], point['lat'], point['lng'],
        protocol_index[point['protocol']], point['gps_seq'], point['seq_gap'],
    ] for point in pts]
    marker_rows = [[
        marker['seq'], marker['t_rel_s'], marker['lat'], marker['lng'],
        marker['protocol_index'], marker['counts'],
    ] for marker in grouped.values()]
    indoor = active['indoor']
    result_params = {**f, 'limit': limit, 'compact': True}
    result_basis = {
        'generation': active.get('generation'), 'total': total,
        'returned': len(pts),
        'first_seq': pts[0]['seq'] if pts else None,
        'last_seq': pts[-1]['seq'] if pts else None,
    }
    return dict(
        project_id=project_id, capture_id=capture_id,
        result_id=svc.result_id(project_id, capture_id, result_basis, result_params),
        format='compact-v1', point_fields=POINT_FIELDS,
        marker_fields=MARKER_FIELDS, protocols=protocols,
        points=point_rows, markers=marker_rows,
        positioned_count=sum(p['lat'] is not None and p['lng'] is not None for p in pts),
        indoor=indoor, floorplan_id=None,
        reason='Plan non renseigné, pas de position' if indoor else None,
        total=total, returned=len(pts), truncated=limit is not None and total > limit,
    )

class RadioValue(BaseModel):
    time_gap_s:float|None
    temporal_relation:Literal['unavailable','same_timestamp','previous_timestamp']
    value:float|None
    unit:str
    source:str
    seq:int|None
    seq_gap:int|None
    reason:str|None=None

class Context(Envelope):
    seq:int
    radio:dict[str,RadioValue]
    ecgi:str|None
    ecgi_seq_gap:int|None
    enb_gnb_id:str|None=None
    sector:str|None=None
    identity_reason:str='Site/sector mapping not provided by the capture reference contract'

class Details(Envelope):
    seq:int
    tree:dict[str,Any]
    parameters:list[dict[str,Any]]
    text:str
    hex:str|None
    hex_reason:str|None
    tree_source:str
    tree_route_gap:str


def filters(protocols:str|None=None,direction:Literal['UL','DL','unknown']|None=None,q:str|None=Query(None,max_length=200),procedure:str|None=None,technology:Literal['LTE','NR']|None=None,from_s:float|None=Query(None,ge=0),to_s:float|None=Query(None,ge=0)):
    if from_s is not None and to_s is not None and from_s>to_s:raise HTTPException(422,'invalid_time_range')
    return dict(protocols=protocols,direction=direction,q=q,procedure=procedure,technology=technology,from_s=from_s,to_s=to_s)


def envelope(pid,cap,rows,params):
    return dict(project_id=pid,capture_id=cap,result_id=svc.result_id(pid,cap,rows,params))

@router.get('/captures',response_model=Captures)
def captures(project_id:str,db:Session=Depends(get_db)):
    project(db,project_id)
    cached = _CAPTURES_CACHE.get(project_id)
    if cached and time.monotonic() - cached[0] < 60:
        return dict(project_id=project_id,captures=cached[1])
    # 0.76.1 — expose kind depuis nmf_capture (LEFT JOIN : capture non encore
    # décodée → kind=NULL). Jamais inventé.
    rows=svc.query(db,'''SELECT DISTINCT r.capture_id,n.filename AS label,n.env,c.kind FROM stg_event_raw r
       JOIN nmf_file n ON n.id=r.nmf_file_id
       LEFT JOIN nmf_capture c ON c.project_id=r.project_id AND c.capture_id=r.capture_id
       WHERE r.project_id=:pid ORDER BY r.capture_id''',dict(pid=project_id))
    _CAPTURES_CACHE[project_id] = (time.monotonic(), rows)
    return dict(project_id=project_id,captures=rows)

@router.get('',response_model=Lines)
def lines(project_id:str,capture_id:str,page:int=Query(1,ge=1),size:int=Query(100,ge=1,le=500),seq:int|None=None,sort:Literal['seq','t_rel_s','protocol','message_name','size_bytes']='seq',order:Literal['asc','desc']='asc',f:dict=Depends(filters),db:Session=Depends(get_db)):
    rows,procedures,_,_=svc.population(db,project_id,capture_id)
    selected=svc.filtered(rows,**f)
    selected.sort(key=lambda r:(r[sort] is None,r[sort],r['seq']),reverse=order=='desc')
    selected_page=next((i//size+1 for i,r in enumerate(selected) if r['seq']==seq),None)
    if selected_page:page=selected_page
    protocol_counts={p:sum(r['protocol']==p for r in rows) for p in svc.PROTOCOLS}
    return dict(**envelope(project_id,capture_id,selected,{**f,'sort':sort,'order':order,'page':page,'size':size}),
      rows=selected[(page-1)*size:page*size],total=len(selected),page=page,size=size,pages=math.ceil(len(selected)/size),
      protocol_counts=protocol_counts,layer_counts={svc.LAYER_FOR_PROTOCOL[p]:c for p,c in protocol_counts.items()},
      procedures=procedures,selected_page=selected_page)

@router.get('/timeline',response_model=Timeline)
def timeline(project_id:str,capture_id:str,bucket_s:float=Query(1,gt=0,le=3600),f:dict=Depends(filters),db:Session=Depends(get_db)):
    overview=mat.read_timeline(db,project_id,capture_id,bucket_s=bucket_s,**f)
    return dict(**envelope(project_id,capture_id,overview,{**f,'bucket_s':bucket_s}),**overview)

@router.get('/points',response_model=Points)
def points(project_id:str,capture_id:str,limit:int|None=Query(None,ge=1,le=10000),compact:bool=False,f:dict=Depends(filters),db:Session=Depends(get_db)):
    pts,total,active=mat.read_points(db,project_id,capture_id,limit=limit,**f)
    if compact:
        return ORJSONResponse(compact_points_payload(
            project_id, capture_id, pts, total, active, f, limit,
        ))
    indoor=active['indoor'];truncated=limit is not None and total>limit
    grouped={}
    for p in pts:
        if p['lat'] is None or p['lng'] is None:continue
        key=p['gps_seq']
        if key not in grouped:grouped[key]={**p,'counts':{x:0 for x in svc.PROTOCOLS},'seqs':[]}
        grouped[key]['counts'][p['protocol']]+=1
        grouped[key]['seqs'].append(p['seq'])
    return dict(**envelope(project_id,capture_id,pts,{**f,'limit':limit}),points=pts,markers=list(grouped.values()),positioned_count=sum(p["lat"] is not None and p["lng"] is not None for p in pts),indoor=indoor,
      total=total,returned=len(pts),truncated=truncated,
      reason='Plan non renseigné, pas de position' if indoor else None)

@router.get('/context',response_model=Context)
def context(project_id:str,capture_id:str,seq:int=Query(...,ge=0),db:Session=Depends(get_db)):
    svc.capture(db,project_id,capture_id)
    radio,cell=svc.context(db,project_id,capture_id,seq)
    refs=svc.query(db,'SELECT DISTINCT enodebid,sector FROM cell_ref WHERE eci=:eci',dict(eci=str(cell['ecgi']))) if cell and cell['ecgi'] else []
    site=refs[0] if len(refs)==1 else {}
    return dict(**envelope(project_id,capture_id,radio,dict(seq=seq)),seq=seq,radio=radio,
      enb_gnb_id=site.get('enodebid'),sector=site.get('sector'),identity_reason='cell_ref unique match' if site else 'No unique proven cell_ref match', 
      ecgi=str(cell['ecgi']) if cell and cell['ecgi'] is not None else None,ecgi_seq_gap=seq-cell['seq'] if cell else None)

@router.get('/details',response_model=Details)
def details(project_id:str,capture_id:str,seq:int=Query(...,ge=0),db:Session=Depends(get_db)):
    svc.capture(db,project_id,capture_id)
    data=svc.details(db,project_id,capture_id,seq)
    return dict(**envelope(project_id,capture_id,data,dict(seq=seq)),seq=seq,**data)

class SignalingEvent(BaseModel):
    """0.70.0 — Timeline événements. Un événement = un marker BC2 ou une
    procédure reconstruite. Les règles de linkage (pivot/linked/seq_gap)
    sont déclarées dans app.signaling.links et appliquées capture-local."""
    id:str
    lane:Literal['radio','connexion','mobilite','endc','ca','services','acces','contexte']
    type:str
    kind:Literal['mark','bar','band','fail','tri','x']
    seq:int
    seq_end:int|None
    t_rel_s:float|None
    t_rel_end_s:float|None
    duration_ms:float|None
    outcome:Literal['ok','fail','incomplete']|None
    cause:str|None
    label:str
    attrs:dict[str,Any]
    pivot_seq:int|None
    linked_seqs:list[int]
    link_rule:str
    seq_gap:int|None
    context_id:int|None=None
    session_id:str|None=None

class EventsResponse(Envelope):
    events:list[SignalingEvent]
    total:int
    lanes:list[str]
    counts_by_lane:dict[str,int]
    link_rule_counts:dict[str,int]
    rule_version:str|None=None
    unavailable:dict[str,str]={}
    missing_time:int=0
    returned:int|None=None
    truncated:bool=False
    next_seq:int|None=None

class EventsSummary(Envelope):
    tracks:list[str]
    counts:dict[str,int]
    event_types:dict[str,int]
    hidden:dict[str,int]
    total:int
    seq_start:int|None
    seq_end:int|None
    t_rel_start_s:float
    t_rel_end_s:float|None

def window_events(events,from_s=None,to_s=None,after_seq=None,limit=None):
    """Deterministic capture-local event window used by the API and guards."""
    ordered=sorted(events,key=lambda e:(e['seq'],e['id']))
    selected=[e for e in ordered if
      (after_seq is None or e['seq']>after_seq) and
      (from_s is None or (e['t_rel_end_s'] if e['t_rel_end_s'] is not None else e['t_rel_s']) is not None
       and (e['t_rel_end_s'] if e['t_rel_end_s'] is not None else e['t_rel_s'])>=from_s) and
      (to_s is None or e['t_rel_s'] is not None and e['t_rel_s']<=to_s)]
    total=len(selected)
    truncated=limit is not None and total>limit
    returned=selected[:limit] if limit is not None else selected
    return returned,total,truncated,(returned[-1]['seq'] if truncated and returned else None),selected

@router.get('/events/summary',response_model=EventsSummary)
def events_summary(project_id:str,capture_id:str,db:Session=Depends(get_db)):
    """Small first-paint contract from the active import-time generation."""
    active=mat.active_capture(db,project_id,capture_id)
    type_rows=db.execute(text("""SELECT type,count(*) AS n
      FROM signaling_materialized_event
      WHERE project_id=:pid AND capture_id=:cap AND generation=:generation
        AND view='legacy'
      GROUP BY type ORDER BY type"""),dict(pid=project_id,cap=capture_id,
        generation=active['generation'])).mappings()
    payload=dict(tracks=active['tracks'],counts=active['event_counts'],
      event_types={row['type']:int(row['n']) for row in type_rows},
      hidden=active['hidden'],total=active['total'],
      seq_start=active['seq_start'],seq_end=active['seq_end'],
      t_rel_start_s=active['t_rel_start_s'],t_rel_end_s=active['t_rel_end_s'])
    return dict(**envelope(project_id,capture_id,payload,dict(kind='events_summary')),**payload)

@router.get('/events',response_model=EventsResponse)
def events(project_id:str,capture_id:str,lanes:str|None=None,failures_only:bool=False,
           view:Literal["legacy","rf"]="legacy",protocols:str|None=None,technology:str|None=None,
           direction:str|None=None,q:str|None=None,types:str|None=None,
           from_s:float|None=Query(None,ge=0),to_s:float|None=Query(None,ge=0),
           after_seq:int|None=Query(None,ge=0),limit:int|None=Query(None,ge=1,le=5000),
           db:Session=Depends(get_db)):
    """0.70.0 — Spec signaling_timeline.html. Retourne les événements
    agrégés (markers BC2 + procedures) avec appartenance stricte (règles
    explicites dans app.signaling.links). Jamais ts, jamais invention."""
    if from_s is not None and to_s is not None and from_s>to_s:
        raise HTTPException(422,'invalid_time_range')
    evs,total,counts,rules=mat.read_events(db,project_id,capture_id,
      lanes=lanes,failures_only=failures_only,view=view,protocols=protocols,
      technology=technology,direction=direction,q=q,types=types,from_s=from_s,to_s=to_s,
      after_seq=after_seq,limit=limit)
    truncated=limit is not None and total>len(evs)
    next_seq=evs[-1]['seq'] if truncated and evs else None
    from app.signaling import rf
    return dict(**envelope(project_id,capture_id,evs,dict(lanes=lanes,failures_only=failures_only,view=view,protocols=protocols,technology=technology,direction=direction,q=q,from_s=from_s,to_s=to_s,after_seq=after_seq,limit=limit)),
      events=evs,total=total,returned=len(evs),truncated=truncated,
      next_seq=next_seq,
      lanes=sorted(counts),counts_by_lane=counts,link_rule_counts=rules,
      rule_version=rf.RULE_VERSION,unavailable=rf.UNAVAILABLE if view=='rf' else {},
      missing_time=sum(e['t_rel_s'] is None for e in evs))

class Procedures(Envelope):
    procedures:list[Procedure]
    total:int
    types:dict[str,int]

@router.get('/procedures',response_model=Procedures)
def procedures(project_id:str,capture_id:str,type:str|None=None,db:Session=Depends(get_db)):
    """Reconstructed procedures (RRC setup, HO, call, data session) for one capture.
    Same live reconstruction as the /signaling response; isolated endpoint so clients
    can list and filter procedures without pulling the full line population."""
    _,procs,_,_=svc.population(db,project_id,capture_id)
    types={p['type']:sum(1 for q in procs if q['type']==p['type']) for p in procs}
    selected=[p for p in procs if type is None or p['type']==type]
    return dict(**envelope(project_id,capture_id,selected,dict(type=type)),
      procedures=selected,total=len(selected),types=types)

class Export(BaseModel):
    csv:str
    filename:str
    result_id:str

@router.get('/export',response_model=Export)
def export(project_id:str,capture_id:str,f:dict=Depends(filters),db:Session=Depends(get_db)):
    rows,_,_,_=svc.population(db,project_id,capture_id)
    rows=svc.filtered(rows,**f)
    rid=svc.result_id(project_id,capture_id,rows,f)
    output=io.StringIO();writer=csv.writer(output)
    keys=['seq','t_rel_s','protocol','direction','message_name','ecgi','pci','size_bytes','procedure_id']
    writer.writerow(['result_id','capture_id',*keys])
    for r in rows:writer.writerow([rid,capture_id,*[r[k] for k in keys]])
    return dict(csv=output.getvalue(),filename='signaling.csv',result_id=rid)
