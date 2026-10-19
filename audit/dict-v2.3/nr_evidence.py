"""Read only NR SIB1 source proof. Never serializes complete decoded PDUs."""
import json,datetime
from pathlib import Path
from sqlalchemy import text
from app.db import engine
from app.dict.decode import resolve_pdu
pid='4b7bfd50ddb6'
q="""SELECT DISTINCT e.id,e.capture_id,e.seq,e.system,e.channel,e.direction,e.message,e.payload_hex
FROM stg_event e JOIN param_occurrence p ON p.stg_event_id=e.id AND p.project_id=e.project_id
WHERE p.project_id=:pid AND p.system='NR' AND p.path LIKE 'systemInformationBlockType1/%'
ORDER BY e.capture_id,e.seq"""
countq="""SELECT count(DISTINCT e.capture_id) captures,count(DISTINCT e.id) events FROM stg_event e JOIN param_occurrence p ON p.stg_event_id=e.id AND p.project_id=e.project_id WHERE p.project_id=:pid AND p.system='NR' AND p.path LIKE 'systemInformationBlockType1/%'"""
setupq="SELECT count(DISTINCT e.capture_id) captures,count(DISTINCT e.id) events FROM stg_event e JOIN param_occurrence p ON p.stg_event_id=e.id AND p.project_id=e.project_id WHERE p.project_id=:pid AND p.system='NR' AND p.path LIKE 'rrcSetup/%'"
def find_sib(v):
 if isinstance(v,dict):
  if 'systemInformationBlockType1' in v:return v['systemInformationBlockType1']
  for x in v.values():
   found=find_sib(x)
   if found is not None:return found
 if isinstance(v,(tuple,list)):
  if len(v)==2 and v[0]=='systemInformationBlockType1':return v[1]
  for x in v:
   found=find_sib(x)
   if found is not None:return found
 return None
with engine.connect() as db:
 proof=[]
 for r in db.execute(text(q),{'pid':pid}).mappings():
  pdu=resolve_pdu(r['system'],r['channel'],r['direction'],r['message']);pdu.from_uper(bytes.fromhex(r['payload_hex']));sib=find_sib(pdu.get_val())
  groups=[]
  for g in (sib or {}).get('cellAccessRelatedInfo',{}).get('plmn-IdentityInfoList',[]):
   cell=g.get('cellIdentity');plmns=g.get('plmn-IdentityList',[])
   # Cell identity is a network identifier. No subscriber fields are exported.
   groups.append({'cellIdentity':cell[0] if isinstance(cell,tuple) else None,'bit_length':cell[1] if isinstance(cell,tuple) else None,'plmns':[{k:p.get(k) for k in ('mcc','mnc')} for p in plmns],'ncgi_readable':isinstance(cell,tuple) and cell[1]==36 and any(p.get('mcc') and p.get('mnc') for p in plmns)})
  proof.append(dict(event_id=r['id'],capture_id=r['capture_id'],seq=r['seq'],groups=groups))
 report=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_id=pid,parameters={'pid':pid},source_sql=q,count_sql=countq,counts=dict(db.execute(text(countq),{'pid':pid}).mappings().one()),setup_sql=setupq,setup=dict(db.execute(text(setupq),{'pid':pid}).mappings().one()),proof=proof)
 Path('audit/dict-v2.3/nr-sa-proof.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_sql','count_sql','setup_sql')},ensure_ascii=False))
