"""0.54.3: two authorized TEST2 captures only. Default dry-run with rollback."""
import sys,json,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
from app.measure.cellmeas_repair import enrich_lte_cellmeas
from app.scripts.deploy_guard import guard_bc3_deploy_lock
pid='134af70a06eb';captures=['ff6a1a2d0d13','e56b56456e0c']
if '--apply' in sys.argv and not guard_bc3_deploy_lock(action='repair_cellmeas_0543'):
 raise SystemExit(1)
with engine.connect() as conn:
 tx=conn.begin();db=Session(bind=conn,join_transaction_mode='create_savepoint')
 def q(sql):
  return dict(sql=sql,parameters={'pid':pid,'captures':captures},rows=[dict(r) for r in db.execute(text(sql),{'pid':pid,'captures':captures}).mappings()])
 other="SELECT md5(string_agg(to_jsonb(m)::text,',' ORDER BY m.id)) hash FROM measurement_points m WHERE project_id=:pid AND (capture_id IS NULL OR NOT(capture_id=ANY(:captures)))"
 inside="SELECT md5(string_agg(to_jsonb(m)::text,',' ORDER BY m.id)) hash FROM measurement_points m WHERE project_id=:pid AND capture_id=ANY(:captures)"
 profiles="SELECT count(*) n,max(id) max_id FROM cellmeas_profile WHERE project_id=:pid"
 counts="""SELECT r.system,count(*) samples,count(s.rsrp) rsrp FROM task_sample s JOIN task_run t ON t.id=s.task_id JOIN stg_event_raw r ON r.project_id=t.project_id AND r.capture_id=t.capture_id AND r.seq=s.mp_seq AND r.event_code='CELLMEAS' WHERE t.project_id=:pid GROUP BY r.system ORDER BY r.system"""
 before=q(other);profile_before=q(profiles);old=q(counts)
 result=enrich_lte_cellmeas(db,pid,captures);first=q(inside)
 enrich_lte_cellmeas(db,pid,captures);second=q(inside)
 assert first==second,'Non-idempotent enrichment'
 update="""UPDATE task_sample s SET rsrp=m.rsrp,rsrq=m.rsrq,sinr=m.sinr,rat=m.rat,earfcn=m.earfcn
 FROM task_run t,measurement_points m WHERE s.task_id=t.id AND t.project_id=:pid
 AND t.capture_id=ANY(:captures) AND m.project_id=t.project_id AND m.capture_id=t.capture_id
 AND m.seq=s.mp_seq AND m.event_code='CELLMEAS'"""
 refreshed=db.execute(text(update),{'pid':pid,'captures':captures}).rowcount
 after=q(other);profile_after=q(profiles)
 assert before==after,'Out-of-scope measurement changed'
 assert profile_before==profile_after,'Profile table changed'
 evidence=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),apply='--apply' in sys.argv,result=result,
  samples_updated=refreshed,update_sql=update,before=old,after=q(counts),other_before=before,other_after=after,
  profiles_before=profile_before,profiles_after=profile_after,idempotent=first==second)
 db.commit()
 if '--apply' in sys.argv:tx.commit()
 else:tx.rollback()
 print(json.dumps(evidence,indent=2,default=str))
