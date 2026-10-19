"""Capture-local measured chronograms, with replayable provenance."""
import csv
import io
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
from app.routes.tasks import project, evidence, filters

router = APIRouter(tags=['metrics'], dependencies=[Depends(get_current_user)])
class MetricInfo(BaseModel):
    code: str
    label: str
    unit: str
    source_table: str
    source_column: str
    tech: Literal['LTE','NR','BOTH']
    kind: Literal['numeric','categorical']
    n_in_project: int
    decoder_version: str = "1.0.0"
    event_code: str = ""
    proof_ref: str = ""
class CaptureInfo(BaseModel):
    capture_id: str
    label: str
class Sample(BaseModel):
    seq: int
    t_rel_s: float
    value: float | str
    tooltip: str = ''
class Sampling(BaseModel):
    method: str
    factor: float
    seq_bucket_width: int | None = None
class Segment(BaseModel):
    start_s: float
    end_s: float
    value: str
class MetricSeries(BaseModel):
    code: str
    label: str
    unit: str
    kind: Literal['numeric','categorical']
    n_total: int
    n_returned: int
    sampling: Sampling
    states: list[str]
    segments: list[Segment]
    points: list[Sample]
class SeriesResponse(BaseModel):
    project_id: str
    capture_id: str
    result_id: str
    origin_seq: int
    origin_ts: str
    duration_s: float
    series: list[MetricSeries]
    csv: str
    time_policy: str
class Marker(BaseModel):
    seq: int
    t_rel_s: float
    type: Literal['task','ho','rlf','rrc']
    label: str
class EventsResponse(BaseModel):
    project_id: str
    capture_id: str
    result_id: str
    markers: list[Marker]

@router.get('/projects/{project_id}/metrics', response_model=list[MetricInfo])
def catalog(project_id: str, db: Session=Depends(get_db)):
    project(db,project_id)
    result=[]
    from app.nmf_decoder.schema import fields
    for code,m in metric_catalog(db).items():
        n=db.execute(text('SELECT count(*) FROM ('+m.sql+') source'),{'pid':project_id}).scalar_one()
        if n:
            result.append(dict(code=code,label=m.label,unit=m.unit,source_table=m.source_table,
                source_column=m.source_column,tech=m.tech,kind=m.kind,n_in_project=n,
                event_code=fields()[m.source_column]["event"],proof_ref=fields()[m.source_column]["proof"]))
    return result

@router.get('/projects/{project_id}/metrics/captures', response_model=list[CaptureInfo])
def captures(project_id: str,f: dict=Depends(filters),db: Session=Depends(get_db)):
    project(db,project_id)
    clauses=['m.project_id=:pid','m.capture_id IS NOT NULL'];p={'pid':project_id}
    for key in ('operator','band','rat','tech','service_type','phase','env','dep'):
        if f.get(key):
            clauses.append(f'm.{key}=ANY(:{key})');p[key]=f[key]
    geo=[]
    for key,col in {'dor':'dor','dr':'dr','plaque':'plaque','arcep':'arcep_zone','commune':'commune','insee':'insee'}.items():
        if f.get(key):geo.append(f'c.{col}=ANY(:{key})');p[key]=f[key]
    if geo:clauses.append("m.ecgi_source='sib1_strict_capture_earfcn' AND EXISTS (SELECT 1 FROM cell_ref c WHERE c.eci=m.ecgi AND "+' AND '.join(geo)+')')
    rows=db.execute(text('SELECT DISTINCT m.capture_id FROM measurement_points m WHERE '+' AND '.join(clauses)+' ORDER BY m.capture_id'),p)
    return [dict(capture_id=r[0],label=r[0]) for r in rows]

TIME_SQL = '''SELECT seq,ts FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap
 UNION SELECT seq,ts FROM stg_event WHERE project_id=:pid AND capture_id=:cap ORDER BY seq'''
def clock(db,pid,cap):
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
def series(project_id: str,capture_id: str,codes: str,from_seq: int|None=Query(None,ge=0),to_seq: int|None=Query(None,ge=0),max_points: int=Query(5000,ge=2,le=100000),db: Session=Depends(get_db)):
    project(db,project_id)
    definitions=metric_catalog(db)
    selected=list(dict.fromkeys(codes.split(',')))
    allowed={m['code'] for m in catalog(project_id,db)}
    if any(c not in allowed for c in selected):raise HTTPException(422,dict(reason='unknown_metric',allowed=sorted(allowed)))
    if from_seq is not None and to_seq is not None and from_seq>to_seq:raise HTTPException(422,'from_seq_after_to_seq')
    times,origin_seq,origin_ts=clock(db,project_id,capture_id)
    params={'pid':project_id,'cap':capture_id,'lo':from_seq,'hi':to_seq}
    sqls=[];results=[];all_values={}
    for code in selected:
        m=definitions[code]
        sql='SELECT seq,value FROM ('+m.sql+') source WHERE capture_id=:cap AND (CAST(:lo AS integer) IS NULL OR seq>=:lo) AND (CAST(:hi AS integer) IS NULL OR seq<=:hi) ORDER BY seq'
        sqls.append(sql)
        rows=db.execute(text(sql),params).mappings().all()
        if any(r['seq'] not in times for r in rows):raise HTTPException(409,dict(reason='metric_timestamp_missing',code=code))
        points=[dict(seq=r['seq'],t_rel_s=times[r['seq']],value=str(r['value']) if m.kind=='categorical' else float(r['value'])) for r in rows]
        for p in points:all_values.setdefault(p['seq'],{})[code]=p['value']
        out,sampling=sample(points,max_points,m.kind)
        segments=[dict(start_s=p['t_rel_s'],end_s=out[i+1]['t_rel_s'] if i+1<len(out) else points[-1]['t_rel_s'],value=p['value']) for i,p in enumerate(out)] if m.kind=='categorical' else []
        results.append(dict(segments=segments,code=code,label=m.label,unit=m.unit,kind=m.kind,n_total=len(points),n_returned=len(out),sampling=sampling,states=list(dict.fromkeys(p['value'] for p in points)) if m.kind=='categorical' else [],points=out))
    for result in results:
        for p in result['points']:
            p['tooltip']='seq '+str(p['seq'])+' · '+str(p['t_rel_s'])+' s\n'+'\n'.join(definitions[c].label+': '+str(all_values[p['seq']].get(c,'N/D'))+' '+definitions[c].unit for c in selected)
    rid=evidence(db,project_id,';\n'.join([TIME_SQL,*sqls]),{**params,'codes':selected,'max_points':max_points},{'series':[{k:r[k] for k in ('code','n_total','n_returned','sampling')} for r in results]})
    output=io.StringIO();writer=csv.writer(output);writer.writerow(['result_id','capture_id','code','unit','seq','t_rel_s','value'])
    for r in results:
        for p in r['points']:writer.writerow([rid,capture_id,r['code'],r['unit'],p['seq'],p['t_rel_s'],p['value']])
    return dict(project_id=project_id,capture_id=capture_id,result_id=rid,origin_seq=origin_seq,origin_ts=origin_ts,duration_s=max(times.values()),series=results,csv=output.getvalue(),time_policy='ts - premier ts valide en ordre seq ; égalités conservées ; régression rejetée ; aucune interpolation')

EVENT_SQL = '''SELECT e.seq,e.message, EXISTS(SELECT 1 FROM param_occurrence p WHERE p.project_id=:pid AND p.stg_event_id=e.id AND p.path LIKE '%mobilityControlInfo%') mobility
 FROM stg_event e WHERE e.project_id=:pid AND e.capture_id=:cap AND e.message IN
 ('RRCConnectionReconfiguration','RRCConnectionReestablishmentRequest','RRCConnectionSetup','RRCConnectionRelease','RRCSetup','RRCRelease') ORDER BY e.seq'''
TASK_SQL = 'SELECT seq_daa,seq_dcomp,task_type FROM task_run WHERE project_id=:pid AND capture_id=:cap ORDER BY seq_start'
@router.get('/projects/{project_id}/captures/{capture_id}/events',response_model=EventsResponse)
def events(project_id: str,capture_id: str,types: str='task,ho,rlf,rrc',db: Session=Depends(get_db)):
    project(db,project_id);wanted=set(types.split(','))
    if not wanted<={'task','ho','rlf','rrc'}:raise HTTPException(422,dict(allowed=['task','ho','rlf','rrc']))
    times,_,_=clock(db,project_id,capture_id);params={'pid':project_id,'cap':capture_id};markers=[]
    def add(seq,kind,label):
        if seq is None:return
        if seq not in times:raise HTTPException(409,dict(reason='event_timestamp_missing',seq=seq))
        markers.append(dict(seq=seq,t_rel_s=times[seq],type=kind,label=label))
    if 'task' in wanted:
        for r in db.execute(text(TASK_SQL),params).mappings():
            for key,label in [('seq_daa','DAA'),('seq_dcomp','DCOMP')]:add(r[key],'task',label+' · '+r['task_type'])
    if wanted-{'task'}:
        for r in db.execute(text(EVENT_SQL),params).mappings():
            name=r['message'];kind='ho' if name=='RRCConnectionReconfiguration' and r['mobility'] else 'rlf' if name=='RRCConnectionReestablishmentRequest' else 'rrc' if name in ('RRCConnectionSetup','RRCConnectionRelease','RRCSetup','RRCRelease') else None
            if kind in wanted:add(r['seq'],kind,name)
    markers.sort(key=lambda r:(r['seq'],r['type'],r['label']))
    rid=evidence(db,project_id,';\n'.join([TIME_SQL,TASK_SQL,EVENT_SQL]),{**params,'types':sorted(wanted)},{'markers':len(markers)})
    return dict(project_id=project_id,capture_id=capture_id,result_id=rid,markers=markers)
