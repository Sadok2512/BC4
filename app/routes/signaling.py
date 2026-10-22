"""Signaling View contract. All observations belong to one explicit capture."""
import csv
import io
import math
import time
from collections import Counter, defaultdict
from typing import Literal, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.routes.tasks import project
from app.signaling import service as svc

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

class Timeline(Envelope):
    buckets:list[Bucket]
    bucket_s:float
    total:int
    missing_time:int

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
    rows=svc.query(db,'''SELECT DISTINCT r.capture_id,n.filename AS label,n.env FROM stg_event_raw r
       JOIN nmf_file n ON n.id=r.nmf_file_id WHERE r.project_id=:pid ORDER BY r.capture_id''',dict(pid=project_id))
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
    rows,_,_,_=svc.population(db,project_id,capture_id)
    rows=svc.filtered(rows,**f)
    counts=defaultdict(Counter)
    for r in rows:
        if r['t_rel_s'] is not None:counts[math.floor(r['t_rel_s']/bucket_s)*bucket_s][r['protocol']]+=1
    buckets=[dict(t_rel_s=t,counts={p:c[p] for p in svc.PROTOCOLS}) for t,c in sorted(counts.items())]
    return dict(**envelope(project_id,capture_id,rows,{**f,'bucket_s':bucket_s}),buckets=buckets,bucket_s=bucket_s,total=len(rows),missing_time=sum(r['t_rel_s'] is None for r in rows))

@router.get('/points',response_model=Points)
def points(project_id:str,capture_id:str,f:dict=Depends(filters),db:Session=Depends(get_db)):
    rows,_,meta,_=svc.population(db,project_id,capture_id)
    rows=svc.filtered(rows,**f)
    pts,indoor=svc.gps_points(db,project_id,capture_id,rows,meta)
    grouped={}
    for p in pts:
        if p['lat'] is None or p['lng'] is None:continue
        key=p['gps_seq']
        if key not in grouped:grouped[key]={**p,'counts':{x:0 for x in svc.PROTOCOLS},'seqs':[]}
        grouped[key]['counts'][p['protocol']]+=1
        grouped[key]['seqs'].append(p['seq'])
    return dict(**envelope(project_id,capture_id,pts,f),points=pts,markers=list(grouped.values()),positioned_count=sum(p["lat"] is not None and p["lng"] is not None for p in pts),indoor=indoor,
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

@router.get('/events',response_model=EventsResponse)
def events(project_id:str,capture_id:str,lanes:str|None=None,failures_only:bool=False,
           view:Literal["legacy","rf"]="legacy",protocols:str|None=None,technology:str|None=None,
           direction:str|None=None,q:str|None=None,db:Session=Depends(get_db)):
    """0.70.0 — Spec signaling_timeline.html. Retourne les événements
    agrégés (markers BC2 + procedures) avec appartenance stricte (règles
    explicites dans app.signaling.links). Jamais ts, jamais invention."""
    from app.signaling import rf
    if view == 'rf':
        evs,_=rf.events(db,project_id,capture_id,protocols,technology,direction,q)
        if failures_only:evs=[e for e in evs if e['outcome']=='fail']
        if lanes is not None:evs=[e for e in evs if e['lane'] in lanes.split(',')]
    else:
        evs,_=svc.events(db,project_id,capture_id,lanes=lanes,failures_only=failures_only)
        # The default legacy view is still consumed by Signaling V2.  Enrich
        # only exact, proven LTE Connected procedures; do not infer sessions
        # for markers, partial pairs, NR, NSA or SA.
        evidence,_=rf.events(db,project_id,capture_id)
        evs=rf.enrich_legacy_connected_events(evs,evidence,capture_id)
    counts={}
    for e in evs:counts[e['lane']]=counts.get(e['lane'],0)+1
    rules={}
    for e in evs:rules[e['link_rule']]=rules.get(e['link_rule'],0)+1
    return dict(**envelope(project_id,capture_id,evs,dict(lanes=lanes,failures_only=failures_only,view=view,protocols=protocols,technology=technology,direction=direction,q=q)),
      events=evs,total=len(evs),lanes=sorted(counts),counts_by_lane=counts,link_rule_counts=rules,
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
