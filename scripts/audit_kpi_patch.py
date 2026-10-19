"""Live SQL evidence. --preview migrates and rolls back."""
import sys,json,datetime,importlib.util
from pathlib import Path
from sqlalchemy import text
from app.db import engine
from app.services.task_run import seconds
out=Path('audit/task_run/0.54.1');out.mkdir(parents=True,exist_ok=True)
pid='134af70a06eb'
with engine.connect() as conn:
 tx=conn.begin()
 if '--preview' in sys.argv:
  from alembic.migration import MigrationContext
  from alembic.operations import Operations
  spec=importlib.util.spec_from_file_location('patch','alembic/versions/0027_task_pairing.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  m.op=Operations(MigrationContext.configure(conn));m.upgrade()
 def query(sql,params=None):
  p=params or {'pid':pid}
  return dict(sql=sql,parameters=p,rows=[dict(r) for r in conn.execute(text(sql),p).mappings()])
 evidence={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'project_id':pid}
 evidence['counts']=query('SELECT count(*),count(rsrp) rsrp,count(sinr) sinr,count(cqi) cqi FROM task_sample WHERE task_id IN (SELECT id FROM task_run WHERE project_id=:pid)')
 evidence['status']=query('SELECT status,reason,count(*) n FROM task_run WHERE project_id=:pid GROUP BY status,reason ORDER BY status,reason')
 evidence['gaps']=query('SELECT percentile_cont(ARRAY[.5,.9]) WITHIN GROUP(ORDER BY s.seq_gap) all_radio,percentile_cont(ARRAY[.5,.9]) WITHIN GROUP(ORDER BY s.seq_gap) FILTER(WHERE s.rsrp IS NOT NULL) rsrp FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid')
 evidence['previous_rsrp']=query('SELECT percentile_cont(ARRAY[.5,.9]) WITHIN GROUP(ORDER BY s.seq-m.seq) gaps FROM task_sample s JOIN task_run t ON t.id=s.task_id JOIN LATERAL (SELECT seq FROM measurement_points WHERE project_id=t.project_id AND capture_id=t.capture_id AND seq<s.seq AND rsrp IS NOT NULL ORDER BY seq DESC LIMIT 1) m ON true WHERE t.project_id=:pid')
 raw=json.loads(Path('../handoff-bc2-g14-0.54.1/five-worst-raw.json').read_text());five=[]
 for t in raw:
  rows=t['raw'];dr=[r for r in rows if r['event_code']=='DRATE'];daa=next(r for r in rows if r['event_code']=='DAA');dc=next(r for r in rows if r['event_code']=='DCOMP');times=[seconds(r['raw_fields']['ts']) for r in dr]
  threads=query('SELECT threads FROM task_run WHERE project_id=:pid AND capture_id=:cap AND seq_start=:start',{'pid':pid,'cap':t['capture_id'],'start':t['seq_start']})
  five.append(dict(id=t['id'],capture_id=t['capture_id'],seq_start=t['seq_start'],integral_ratio=t['integral_ratio'],first_after_daa_s=float(times[0]-seconds(daa['raw_fields']['ts'])),max_internal_interval_s=float(max((b-a for a,b in zip(times,times[1:])),default=0)),stop_before_dcomp_s=float(seconds(dc['raw_fields']['ts'])-times[-1]),first_before_daa=dr[0]['seq']<daa['seq'],threads=threads,source_sql=t['source_sql'],source_parameters=t['source_parameters']))
 evidence['five_worst']=five
 (out/('preview.json' if '--preview' in sys.argv else 'live.json')).write_text(json.dumps(evidence,indent=2,default=str)+'\n')
 print(json.dumps({k:v for k,v in evidence.items() if k!='five_worst'},default=str))
 tx.rollback()
