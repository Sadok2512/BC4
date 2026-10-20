"""Read-only: docker exec -i bc4-api-1 python < signaling-time-audit/audit.py."""
import csv, json, os, sys, hashlib
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import text
from app.db import SessionLocal
from app.routes.metrics import clock,TIME_SQL
from app.signaling.service import population
sys.path.insert(0,'/opt/nmf_decoder')
import bc4_decoder
PID='134af70a06eb';CAP='1e4e8d879a83'
q="SELECT n.id,n.filename FROM nmf_file n WHERE id IN (SELECT nmf_file_id FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap)"
with SessionLocal() as db:
 file=dict(db.execute(text(q),dict(pid=PID,cap=CAP)).mappings().one())
 path=f"/var/lib/bc4/nmf-source/{PID}/{file['id']}.nmf"
 raw=open(path,'rb').read();sources={};seq=0
 for lineno,line in enumerate(raw.decode('latin-1').splitlines(),1):
  if not line or line.startswith('#'):continue
  fields=bc4_decoder._fields(line)
  if not fields:continue
  seq+=1;sources[seq]={'line':lineno,'event_code':fields[0],'ts':fields[1] if len(fields)>1 else None}
 staged=[dict(r) for r in db.execute(text(TIME_SQL),dict(pid=PID,cap=CAP)).mappings()]
 mismatch=[{'seq':r['seq'],'stored':r['ts'],'source':sources[r['seq']]['ts']} for r in staged if r['ts']!=sources[r['seq']]['ts']]
 times,origin_seq,origin_ts=clock(db,PID,CAP)
 def seconds(ts):
  h,m,s=ts.split(':');return Decimal(h)*3600+Decimal(m)*60+Decimal(s)
 rows,_,_,_=population(db,PID,CAP,persist=False)
 diffs=[r['seq'] for r in rows if r['t_rel_s']!=float(seconds(sources[r['seq']]['ts'])-seconds(origin_ts))]
 witnesses=[r for r in rows if r['seq'] in [65,67,69,71,72,84,85]]
 nonzero=next(r for r in rows if r['t_rel_s'] and r['t_rel_s']%1)
 witnesses.append(nonzero)
 report={'at':datetime.now(timezone.utc).isoformat(),'project':PID,'capture':CAP,'sql':{'file':q,'times':TIME_SQL},'source_file':file,'source_path':path,'sha256':hashlib.sha256(raw).hexdigest(),'origin_seq':origin_seq,'origin_ts':origin_ts,'unit':'seconds; source milliseconds','staged_rows':len(staged),'staged_source_diff':mismatch,'signaling_total':len(rows),'source_relative_diff':diffs,'zero_messages':sum(r['t_rel_s']==0 for r in rows),'missing_messages':sum(r['t_rel_s'] is None for r in rows),'witnesses':[{'seq':r['seq'],'message':r['message_name'],'t_rel_s':r['t_rel_s'],**sources[r['seq']]} for r in witnesses]}
 print(json.dumps(report,indent=2))
 assert not mismatch and not diffs
