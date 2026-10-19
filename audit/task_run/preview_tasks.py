from app.db import SessionLocal
from app.services.task_run import load_tasks,EVENT_SQL
from app.services.task_privacy import PRIVACY_SELECT,redact_command
from sqlalchemy import text
import json
with SessionLocal() as db:
 changed={};errors=0
 for row in db.execute(text(PRIVACY_SELECT)).mappings():
  safe=redact_command(row['raw_fields'])
  if safe!=row['raw_fields']:changed[row['project_id']]=changed.get(row['project_id'],0)+1
 print(json.dumps(dict(privacy_select=PRIVACY_SELECT,would_redact=changed)))
 for pid in ['134af70a06eb','4b7bfd50ddb6']:
  ts=load_tasks(db,pid);bad=[];ratios=[]
  for t in ts:
   if t['bytes_dcomp'] and t['_samples']:
    values=[s['bytes_cum'] for s in t['_samples'] if s['bytes_cum'] is not None]
    last=values[-1] if values else None
    total=sum(values) if values else None
    ratios.append(dict(task_id=t['id'],capture_id=t['capture_id'],seq=t['seq_start'],bytes_dcomp=t['bytes_dcomp'],sum_bytes=total,last_bytes=last,first_bytes=values[0] if values else None,n_samples=len(values)))
  from collections import Counter
  print(json.dumps(dict(project_id=pid,sql=EVENT_SQL,tasks=len(ts),samples=sum(len(t['_samples']) for t in ts),status=dict(Counter(t['status'] for t in ts)),reasons=dict(Counter(t['reason'] for t in ts)),byte_examples=ratios[:5],byte_guard_last=sum(abs(r['last_bytes']-r['bytes_dcomp'])/r['bytes_dcomp']>.05 for r in ratios),byte_guard_sum=sum(abs(r['sum_bytes']-r['bytes_dcomp'])/r['bytes_dcomp']>.05 for r in ratios))))
