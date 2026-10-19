"""Task analytics: measured DRATE samples, never reconstructed from aggregates."""
import json
import uuid
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user,get_actor,require_role
from app.models import Project
from app.schemas.settings import Actor
from app.kpi.axes import AXES

router=APIRouter(dependencies=[Depends(get_current_user)],tags=['task-analytics'])
VERSION='0.54.3'
CODES={'THR_DL_APP':'HTTP_DL','THR_UL_APP':'HTTP_UL','AGG_APP_DL_THR':'HTTP_DL','AGG_APP_UL_THR':'HTTP_UL'}

class Task(BaseModel):
    id:str;project_id:str;capture_id:str;seq_start:int;seq_end:int
    seq_daa:int|None;seq_dcomp:int|None;task_type:str;host:str|None
    threads:int|None;max_duration_s:float|None;call_duration_s:float|None
    bytes_dcomp:int|None;duration_s:float|None;mos_aqdl:float|None
    operator:str|None;band:str|None;tech:str|None;status:str;reason:str|None
class Population(BaseModel):
    tasks:int;samples:int;admissible:int;returned:int;excluded:int;incomplete_tasks:int=0
class TaskList(BaseModel):
    result_id:str;project_id:str;tasks:list[Task];population:Population
class Point(BaseModel):
    task_id:str|None=None;capture_id:str|None=None;seq:int|None=None;mp_seq:int|None=None;seq_gap:int|None=None
    t_rel_s:float|None=None;x:float|None=None;value:float|None=None
    p10:float|None=None;p50:float|None=None;p90:float|None=None;n:int|None=None
class Excluded(BaseModel):
    nr_no_profile:int=0;lte_not_enriched:int=0;other:int=0

class Analytics(BaseModel):
    result_id:str;project_id:str;code:str;x_metric:str;x_unit:str;y_unit:str
    population:Population;points:list[Point];sampling:dict;pairing:str|None=None
    excluded:Excluded|None=None

def filters(operator:list[str]=Query(default=[]),band:list[str]=Query(default=[]),tech:list[str]=Query(default=[]),rat:list[str]=Query(default=[]),capture_id:str|None=None,
            service_type:list[str]=Query(default=[]),phase:list[str]=Query(default=[]),env:list[str]=Query(default=[]),dep:list[str]=Query(default=[]),dor:list[str]=Query(default=[]),dr:list[str]=Query(default=[]),plaque:list[str]=Query(default=[]),arcep:list[str]=Query(default=[]),commune:list[str]=Query(default=[]),insee:list[str]=Query(default=[])):
    return {k:v for k,v in locals().items() if v}

def project(db,pid):
    if not db.get(Project,pid):raise HTTPException(404,'project_not_found')

def where(pid,f):
    clauses=['t.project_id=:pid'];p={'pid':pid}
    for k,col in {'operator':'operator','band':'band','tech':'tech','rat':'tech'}.items():
        if f.get(k):clauses.append(f't.{col}=ANY(:{k})');p[k]=f[k]
    if f.get('capture_id'):clauses.append('t.capture_id=:capture_id');p['capture_id']=f['capture_id']
    if f.get('task_id'):clauses.append('t.id=:task_id');p['task_id']=f['task_id']
    if f.get('type'):clauses.append('t.task_type=:type');p['type']=f['type']
    extra=[]
    for k,col in {'service_type':'service_type','phase':'phase','env':'env','dep':'dep'}.items():
        if f.get(k):extra.append(f'm.{col}=ANY(:{k})');p[k]=f[k]
    geo=[]
    for k,col in {'dor':'dor','dr':'dr','plaque':'plaque','arcep':'arcep_zone','commune':'commune','insee':'insee'}.items():
        if f.get(k):geo.append(f'c.{col}=ANY(:{k})');p[k]=f[k]
    if geo:extra.append("m.ecgi_source='sib1_strict_capture_earfcn' AND EXISTS (SELECT 1 FROM cell_ref c WHERE c.eci=m.ecgi AND "+' AND '.join(geo)+')')
    if extra:clauses.append('EXISTS (SELECT 1 FROM measurement_points m WHERE m.project_id=t.project_id AND m.capture_id=t.capture_id AND m.seq BETWEEN t.seq_start AND t.seq_end AND '+' AND '.join(extra)+')')
    return ' AND '.join(clauses),p

def evidence(db,pid,sql,params,pop):
    rid=str(uuid.uuid4())
    db.execute(text('INSERT INTO task_result(id,project_id,sql,filters,population,version) VALUES (:id,:pid,:sql,CAST(:f AS jsonb),CAST(:p AS jsonb),:v)'),{'id':rid,'pid':pid,'sql':sql,'f':json.dumps(params),'p':json.dumps(pop),'v':VERSION});db.commit()
    return rid

def population(tasks,samples,admissible,returned):return dict(tasks=tasks,samples=samples,admissible=admissible,returned=returned,excluded=samples-admissible)

@router.get('/projects/{project_id}/kpi/axes')
def axes(project_id:str,db:Session=Depends(get_db)):
    project(db,project_id)
    return [dict(code=code,**meta) for code,meta in AXES.items()]

@router.get('/projects/{project_id}/tasks',response_model=TaskList)
def tasks(project_id:str,type:Literal['HTTP_DL','HTTP_UL','VOICE','PING','OTHER']|None=None,f:dict=Depends(filters),db:Session=Depends(get_db)):
    project(db,project_id)
    if type:f['type']=type
    cond,p=where(project_id,f);sql='SELECT t.* FROM task_run t WHERE '+cond+' ORDER BY t.capture_id,t.seq_start'
    rows=[dict(r) for r in db.execute(text(sql),p).mappings()];pop=population(len(rows),len(rows),len(rows),len(rows));pop['incomplete_tasks']=sum(r['status']!='ok' for r in rows)
    return dict(result_id=evidence(db,project_id,sql,p,pop),project_id=project_id,tasks=rows,population=pop)

def samples(db,pid,code,f):
    project(db,pid)
    if code not in CODES:raise HTTPException(422,{'reason':'unsupported_KPI','allowed':list(CODES)})
    f={**f,'type':CODES[code]};cond,p=where(pid,f)
    sql="SELECT s.*,t.capture_id,t.status,r.system AS radio_system,m.rat AS normalized_rat FROM task_sample s JOIN task_run t ON t.id=s.task_id LEFT JOIN stg_event_raw r ON r.project_id=t.project_id AND r.capture_id=t.capture_id AND r.seq=s.mp_seq AND r.event_code='CELLMEAS' LEFT JOIN measurement_points m ON m.project_id=t.project_id AND m.capture_id=t.capture_id AND m.seq=s.mp_seq AND m.event_code='CELLMEAS' WHERE "+cond+' ORDER BY t.capture_id,s.seq'
    return [dict(r) for r in db.execute(text(sql),p).mappings()],sql,p

def axis(x,allowed):
    if x not in allowed:raise HTTPException(422,{'reason':'unsupported_axis','allowed':allowed,'catalog':list(AXES)})

def exclusion_reasons(rows,x,valid):
    admitted={(r['task_id'],r['seq']) for r in valid}
    counts={'nr_no_profile':0,'lte_not_enriched':0,'other':0}
    for r in rows:
        if (r['task_id'],r['seq']) in admitted:continue
        if x=='rsrp' and r.get('rsrp') is None and r.get('radio_system')=='NR':counts['nr_no_profile']+=1
        elif x=='rsrp' and r.get('rsrp') is None and r.get('radio_system')=='LTE' and r.get('normalized_rat') is None:counts['lte_not_enriched']+=1
        else:counts['other']+=1
    return counts

def percentile(values,q):
    values=sorted(values);i=(len(values)-1)*q;lo=int(i);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(i-lo)

@router.get('/projects/{project_id}/kpi/{code}/series',response_model=Analytics)
def series(project_id:str,code:str,x:str='task_time',task_id:str|None=None,f:dict=Depends(filters),db:Session=Depends(get_db)):
    axis(x,['task_time'])
    if task_id:
        f['task_id']=task_id
        if not db.execute(text('SELECT 1 FROM task_run WHERE id=:id AND project_id=:p'),{'id':task_id,'p':project_id}).scalar():raise HTTPException(404,'task_not_in_project')
    rows,sql,p=samples(db,project_id,code,f);valid=[r for r in rows if r['t_rel_s'] is not None and r['t_rel_s']>=0 and r['bps'] is not None and r['bps']>=0]
    if task_id:
        points=[dict(task_id=r['task_id'],capture_id=r['capture_id'],seq=r['seq'],mp_seq=r['mp_seq'],t_rel_s=r['t_rel_s'],value=r['bps']/1e6 if r['bps'] is not None else None) for r in rows]
    else:
        buckets={}
        for r in valid:buckets.setdefault(r['t_rel_s'],[]).append(r['bps']/1e6)
        points=[dict(t_rel_s=t,p10=percentile(v,.1),p50=percentile(v,.5),p90=percentile(v,.9),n=len(v)) for t,v in sorted(buckets.items())]
    pop=population(len({r['task_id'] for r in rows}),len(rows),len(valid),len(points));pop['incomplete_tasks']=len({r['task_id'] for r in rows if r['status']!='ok'})
    return dict(result_id=evidence(db,project_id,sql,p,pop),project_id=project_id,code=code,x_metric=x,x_unit='s',y_unit='Mbit/s',population=pop,points=points,sampling={'method':'none','alignment':'exact decoded t_rel_s; no interpolation'})

@router.get('/projects/{project_id}/kpi/{code}/points',response_model=Analytics)
def points(project_id:str,code:str,x:str='rsrp',limit:int=Query(5000,ge=1,le=5000),f:dict=Depends(filters),db:Session=Depends(get_db)):
    axis(x,list(AXES));rows,sql,p=samples(db,project_id,code,f)
    if x=='cqi':
        for row in rows:
            row['mp_seq']=row['cqi_seq'];row['seq_gap']=row['cqi_seq_gap']
    column={'task_time':'t_rel_s','capture_time':'capture_time_s'}.get(x,x)
    valid=[r for r in rows if r[column] is not None and r['bps'] is not None and r['bps']>=0 and (x in ('task_time','capture_time') or r['mp_seq'] is not None)]
    excluded=exclusion_reasons(rows,x,valid)
    n=len(valid);selected=valid if n<=limit else [valid[(i*n)//limit] for i in range(limit)]
    pts=[dict(task_id=r['task_id'],capture_id=r['capture_id'],seq=r['seq'],mp_seq=r['mp_seq'],seq_gap=r['seq_gap'],x=r[column],value=r['bps']/1e6,t_rel_s=r['t_rel_s']) for r in selected]
    pop=population(len({r['task_id'] for r in rows}),len(rows),n,len(pts));pop['incomplete_tasks']=len({r['task_id'] for r in rows if r['status']!='ok'})
    return dict(result_id=evidence(db,project_id,sql,{**p,'x':x,'limit':limit},pop),project_id=project_id,code=code,x_metric=x,x_unit=AXES[x]['unit'],y_unit='Mbit/s',population=pop,excluded=excluded,points=pts,sampling={'method':'canonical evenly-spaced ranks' if n>limit else 'none','order':['capture_id','seq'],'limit':limit},pairing=('nearest strictly preceding CQI in same capture' if x=='cqi' else 'nearest strictly preceding CELLMEAS in same capture')+'; no task boundary or distance limit; conflicting rows at same seq -> NULL; no interpolation')

@router.get('/results/{result_id}')
def result(result_id:str,actor:Actor=Depends(get_actor),db:Session=Depends(get_db)):
    require_role(actor,'admin')
    r=db.execute(text('SELECT * FROM task_result WHERE id=:id'),{'id':result_id}).mappings().first()
    if not r:raise HTTPException(404,'result_not_found')
    return dict(r)
