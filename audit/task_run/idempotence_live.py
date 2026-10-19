import json
from sqlalchemy import text
from app.db import SessionLocal
from app.services.task_run import populate_tasks
pid='4b7bfd50ddb6'
hash_sql="SELECT md5(string_agg(to_jsonb(s)::text,',' ORDER BY s.task_id,s.seq)) FROM task_sample s JOIN task_run t ON t.id=s.task_id WHERE t.project_id=:pid"
with SessionLocal() as db:
 before=db.execute(text(hash_sql),{'pid':pid}).scalar();result=populate_tasks(db,pid);db.commit();after=db.execute(text(hash_sql),{'pid':pid}).scalar()
 print(json.dumps(dict(project_id=pid,sql=hash_sql,parameters={'pid':pid},before=before,after=after,status='PASS' if before==after else 'FAIL',populate=result)))
 sql="""SELECT count(*) FROM task_sample s JOIN task_run t ON t.id=s.task_id
 WHERE t.project_id=:pid AND s.mp_seq IS NOT NULL AND (s.mp_seq>=s.seq OR NOT EXISTS (
 SELECT 1 FROM measurement_points m WHERE m.project_id=t.project_id AND m.capture_id=t.capture_id
 AND m.seq=s.mp_seq AND m.rsrp IS NOT DISTINCT FROM s.rsrp AND m.rsrq IS NOT DISTINCT FROM s.rsrq
 AND m.sinr IS NOT DISTINCT FROM s.sinr AND m.cqi IS NOT DISTINCT FROM s.cqi))"""
 invalid=db.execute(text(sql),{'pid':pid}).scalar();print(json.dumps(dict(project_id=pid,guard='RADIO_TRACE',sql=sql,parameters={'pid':pid},invalid=invalid,status='PASS' if invalid==0 else 'FAIL')))
