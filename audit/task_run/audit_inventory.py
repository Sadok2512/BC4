"""Read-only staging audit. No payload/identity is printed or exported."""
import csv, io, json, collections, base64, zlib, xml.etree.ElementTree as ET
from sqlalchemy import text
from app.db import SessionLocal
PID='4b7bfd50ddb6'
SQL="""SELECT capture_id,seq,event_code,raw_fields FROM stg_event_raw
WHERE project_id=:pid AND event_code IN ('CMDREQ','DAA','DRATE','DCOMP','DSUMMARY','AQDL') ORDER BY capture_id,seq"""
with SessionLocal() as db:
 rows=db.execute(text(SQL),{'pid':PID}).mappings()
 counts=collections.defaultdict(collections.Counter)
 for cap in db.execute(text('SELECT DISTINCT capture_id FROM stg_event_raw WHERE project_id=:pid'), {'pid':PID}).scalars(): counts[cap]
 tasks=[]; opened={}; tags=collections.Counter(); identity_payloads=0
 def close(cap):
  if cap in opened:
   t=opened.pop(cap);tasks.append(t)
 for r in rows:
  cap=r['capture_id'];ev=r['event_code'];rf=r['raw_fields'];counts[cap][ev]+=1
  if ev=='CMDREQ':
   action=rf.get('service_action') or 'UNKNOWN';counts[cap]['CMDREQ:'+action]+=1
   if action.startswith('StartHTTP') or action in ('VoiceCallStart','ReceiveCallStart','StartPing'):
    close(cap);opened[cap]={'capture_id':cap,'seq_start':r['seq'],'action':action,'DAA':0,'DCOMP':0}
   if action=='VoiceCallStart' and rf.get('payload_b64'):
    try:
     root=ET.fromstring(zlib.decompress(base64.b64decode(rf['payload_b64'])))
     for e in root.iter():tags[e.tag]+=1
     if any(('number' in e.tag.lower() or 'phone' in e.tag.lower()) and (e.text or e.attrib.get('All')) for e in root.iter()): identity_payloads+=1
    except Exception: counts[cap]['voice_payload_decode_error']+=1
  if cap in opened and ev in ('DAA','DCOMP'):opened[cap][ev]+=1
 for cap in list(opened):close(cap)
 headers=['capture_id']+['CMDREQ','DAA','DRATE','DCOMP','DSUMMARY','AQDL']+sorted({k for v in counts.values() for k in v if k.startswith('CMDREQ:')})+['tasks_missing_daa','tasks_missing_dcomp']
 out=io.StringIO();w=csv.DictWriter(out,fieldnames=headers);w.writeheader()
 for cap,c in sorted(counts.items()):
  d={k:c[k] for k in headers if k!='capture_id'};d['capture_id']=cap
  d['tasks_missing_daa']=sum(t['capture_id']==cap and not t['DAA'] for t in tasks)
  d['tasks_missing_dcomp']=sum(t['capture_id']==cap and not t['DCOMP'] for t in tasks)
  w.writerow(d)
 print(json.dumps({'project_id':PID,'sql':SQL,'csv':out.getvalue(),'missing_boundaries':[t for t in tasks if not t['DAA'] or not t['DCOMP']], 'voice_xml_tags':dict(tags),'voice_payloads_with_identity_fields':identity_payloads}))
