import json,datetime
from sqlalchemy import text
from app.db import SessionLocal
from app.services.task_run import populate_tasks,EVENT_SQL
for pid in ['134af70a06eb','4b7bfd50ddb6']:
 with SessionLocal() as db:
  result=populate_tasks(db,pid);db.commit()
  sql='SELECT task_type,status,reason,count(*) n FROM task_run WHERE project_id=:pid GROUP BY 1,2,3 ORDER BY 1,2,3'
  rows=[dict(r) for r in db.execute(text(sql),{'pid':pid}).mappings()]
  print(json.dumps(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_id=pid,source_sql=EVENT_SQL,populate=result,sql=sql,parameters={'pid':pid},populations=rows),ensure_ascii=False),flush=True)
