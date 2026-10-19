"""Manual guards, live data only. --preview applies migration/populate with rollback.
python scripts/_guard_G14_task_run.py [--preview] [project_id]
Live mode requires normal BC4 admin env for authenticated HTTP; tokens never printed.
"""
import sys,json,os,importlib.util,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
from app.services.task_privacy import PRIVACY_SELECT,command_xml,has_private_value
pid=next((x for x in sys.argv[1:] if not x.startswith('--')),'4b7bfd50ddb6')
preview='--preview' in sys.argv

def emit(guard,status,sql,**values):
 print(json.dumps(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_id=pid,guard=guard,status=status,sql=sql,parameters={'pid':pid},**values),ensure_ascii=False,default=str),flush=True)

with engine.connect() as conn:
 tx=conn.begin()
 try:
  if preview:
   from alembic.migration import MigrationContext
   from alembic.operations import Operations
   path=Path(__file__).resolve().parents[1]/'alembic/versions/0026_task_run.py'
   spec=importlib.util.spec_from_file_location('migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
   migration.op=Operations(MigrationContext.configure(conn));migration.upgrade()
  db=Session(bind=conn)
  if preview:
   from app.services.task_run import populate_tasks
   first=populate_tasks(db,pid)
   before=db.execute(text("SELECT md5(string_agg(to_jsonb(s)::text,',' ORDER BY s.task_id,s.seq)) FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid"),{'pid':pid}).scalar()
   second=populate_tasks(db,pid)
   after=db.execute(text("SELECT md5(string_agg(to_jsonb(s)::text,',' ORDER BY s.task_id,s.seq)) FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid"),{'pid':pid}).scalar()
   emit('IDEMPOTENCE','PASS' if first==second and before==after else 'FAIL','populate_tasks twice; md5 ordered task_sample rows',first=first,second=second,sample_hash_before=before,sample_hash_after=after)
  byte_sql="""WITH increments AS (
   SELECT t.id,t.capture_id,t.seq_start,t.bytes_dcomp,s.seq,s.bytes_cum,
    s.bytes_cum-COALESCE(lag(s.bytes_cum) OVER(PARTITION BY t.id ORDER BY s.seq),0) delta
   FROM task_run t JOIN task_sample s ON s.task_id=t.id WHERE t.project_id=:pid), totals AS (
   SELECT id,capture_id,seq_start,bytes_dcomp,sum(delta) drate_bytes,bool_or(delta<0) counter_reset
   FROM increments GROUP BY 1,2,3,4)
   SELECT *,abs(drate_bytes-bytes_dcomp)/NULLIF(bytes_dcomp,0)::float relative_gap
   FROM totals ORDER BY capture_id,seq_start"""
  rows=[dict(r) for r in db.execute(text(byte_sql),{'pid':pid}).mappings()]
  eligible=[r for r in rows if r['bytes_dcomp'] is not None and r['bytes_dcomp']>0 and r['drate_bytes'] is not None]
  failed=[r for r in eligible if r['counter_reset'] or r['relative_gap']>.05]
  emit('G14a','PASS' if eligible and not failed else 'FAIL',byte_sql,eligible=len(eligible),excluded=len(rows)-len(eligible),failed=len(failed),failures=failed,interpretation='DRATE.c8 is cumulative: sum successive increments, no extrapolation to DCOMP.')
  time_sql="""WITH samples AS (SELECT s.*,lag(t_rel_s) OVER(PARTITION BY s.task_id ORDER BY s.seq) previous
   FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid)
   SELECT task_id,seq,t_rel_s,previous FROM samples WHERE t_rel_s IS NULL OR t_rel_s<0 OR t_rel_s<=previous"""
  invalid=[dict(r) for r in db.execute(text(time_sql),{'pid':pid}).mappings()]
  emit('G14b','FAIL' if invalid else 'PASS',time_sql,invalid=invalid)
  daa_sql="SELECT id,capture_id,seq_start FROM task_run WHERE project_id=:pid AND status='ok' AND seq_daa IS NULL"
  invalid=[dict(r) for r in db.execute(text(daa_sql),{'pid':pid}).mappings()]
  emit('G14c','FAIL' if invalid else 'PASS',daa_sql,invalid=invalid)
  task_sql="SELECT t.* FROM task_run t WHERE t.project_id=:pid AND t.task_type='HTTP_DL' AND EXISTS(SELECT 1 FROM task_sample s WHERE s.task_id=t.id) ORDER BY t.capture_id,t.seq_start LIMIT 1"
  task=db.execute(text(task_sql),{'pid':pid}).mappings().first()
  if not task:emit('G14d','NOT RUN',task_sql,reason='No HTTP_DL task with DRATE')
  else:
   source_sql="SELECT seq,(raw_fields->>'c6')::double precision bps FROM stg_event_raw WHERE project_id=:pid AND capture_id=:capture AND seq BETWEEN :start AND :end AND event_code='DRATE' ORDER BY seq"
   params={'pid':pid,'capture':task['capture_id'],'start':task['seq_start'],'end':task['seq_end']}
   raw=[dict(r) for r in db.execute(text(source_sql),params).mappings()]
   if preview:
    from app.routes.tasks import series
    response=series(project_id=pid,code='THR_DL_APP',x='task_time',task_id=task['id'],f={},db=db)
   else:
    import httpx
    with httpx.Client(timeout=120) as client:
     login=client.post('http://127.0.0.1:8000/auth/login',json={'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']});login.raise_for_status()
     url=f"http://127.0.0.1:8000/projects/{pid}/kpi/THR_DL_APP/series"
     res=client.get(url,params={'x':'task_time','task_id':task['id']},headers={'Authorization':'Bearer '+login.json()['token']});res.raise_for_status();response=res.json()
   actual=[(p['seq'],p['value']) for p in response['points']]
   expected=[(r['seq'],r['bps']/1e6 if r['bps'] is not None else None) for r in raw]
   emit('G14d','PASS' if actual==expected else 'FAIL',source_sql,source_parameters=params,task_id=task['id'],raw=raw,response=response)
  remaining=0;undecodable_calls=0
  for row in db.execute(text(PRIVACY_SELECT)).mappings():
   f=row['raw_fields'];payload=f.get('payload_b64')
   if not payload or payload=='***':continue
   try:
    if has_private_value(command_xml(payload)):remaining+=1
   except Exception:
    if 'Call' in str(f.get('service_action')):undecodable_calls+=1
  private_sql="SELECT count(*) FROM task_run WHERE host ~ '^\\+?[0-9][0-9 ()-]{6,}$'"
  task_private=db.execute(text(private_sql)).scalar()
  emit('G14e','PASS' if remaining==0 and undecodable_calls==0 and task_private==0 else 'FAIL',PRIVACY_SELECT,scope='all projects',unmasked_private_payloads=remaining,uninspectable_call_payloads=undecodable_calls,task_private_sql=private_sql,task_phone_hosts=task_private)
 finally:
  tx.rollback()
