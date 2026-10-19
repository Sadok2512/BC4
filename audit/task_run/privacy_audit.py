from app.db import SessionLocal
from app.services.task_privacy import PRIVACY_SELECT,command_xml,PRIVATE_TAGS,local_name,has_private_value
from sqlalchemy import text
from collections import Counter
import json
counts=Counter()
with SessionLocal() as db:
 for r in db.execute(text(PRIVACY_SELECT)).mappings():
  f=r['raw_fields']
  try:
   root=command_xml(f.get('payload_b64'))
   for e in root.iter():
    if local_name(e.tag) in PRIVATE_TAGS:
     counts[(r['project_id'],f.get('service_action'),local_name(e.tag),bool((e.text or '').strip()),tuple((k,bool(v.strip())) for k,v in e.attrib.items()))]+=1
  except Exception:counts[(r['project_id'],f.get('service_action'),'UNDECODABLE')]+=1
print(json.dumps([{'context':k,'count':v} for k,v in counts.items()]))
