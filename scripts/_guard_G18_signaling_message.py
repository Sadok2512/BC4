"""Manual, read-only G18 on TEST2 and Test_3. No raw payload or identity logging.
Run inside API container: python scripts/_guard_G18_signaling_message.py [--http]
--http checks deployed endpoint/OpenAPI, with credentials read only from environment.
"""
import datetime
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import text
from app.db import SessionLocal
from app.dict.signaling_message import decoded_message

PROJECTS = ('134af70a06eb', '4b7bfd50ddb6')
CHOOSE = """SELECT e.capture_id,e.seq,count(*) n FROM param_occurrence p
JOIN stg_event e ON e.id=p.stg_event_id AND e.project_id=p.project_id
WHERE p.project_id=:pid AND e.message='RRCConnectionReconfiguration'
AND NOT COALESCE(p.is_identifier,false)
GROUP BY e.capture_id,e.seq ORDER BY e.capture_id,e.seq LIMIT 1"""
EXPECTED = """SELECT p.path,COALESCE(p.value_converted,p.value) value,p.unit_converted unit,p.display_name
FROM param_occurrence p JOIN stg_event e ON e.id=p.stg_event_id AND e.project_id=p.project_id
WHERE p.project_id=:pid AND e.capture_id=:cap AND e.seq=:seq
AND NOT COALESCE(p.is_identifier,false) ORDER BY p.path"""
RESTRICTED = """SELECT DISTINCT ON(message) capture_id,seq,message FROM stg_event
WHERE project_id=:pid AND message IN ('RRCConnectionRequest','RRCConnectionSetupComplete','ULInformationTransfer','DLInformationTransfer')
ORDER BY message,capture_id,seq"""
SAFE = """SELECT capture_id,seq,message FROM stg_event WHERE project_id=:pid
AND event_code='RRCSM' AND system='LTE' AND channel='BCCH-BCH'
ORDER BY capture_id,seq LIMIT 1"""

client = None
if '--http' in sys.argv:
    client = httpx.Client(base_url=os.environ.get('BC4_API_BASE','http://127.0.0.1:8000'), timeout=90)
    auth = client.post('/auth/login', json={'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']})
    auth.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + auth.json()['token']

report = {'at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'auth':'Bearer (redacted)', 'mode':'http' if client else 'service', 'projects':[]}
failed = False
try:
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SET LOCAL statement_timeout='60s'"))
        def fetch(pid, cap, seq):
            if client:
                r=client.get(f'/projects/{pid}/signaling/message', params={'capture_id':cap,'seq':seq})
                r.raise_for_status()
                return r.json()
            return decoded_message(db,pid,cap,seq).model_dump()
        for pid in PROJECTS:
            record={'project_id':pid}
            sample=db.execute(text(CHOOSE),{'pid':pid}).mappings().first()
            if not sample:
                record['G18a']={'status':'NOT RUN','reason':'No populated RRCConnectionReconfiguration','choose_sql':CHOOSE}
                failed=True
            else:
                params={'pid':pid,'cap':sample['capture_id'],'seq':sample['seq']}
                expected=[dict(r) for r in db.execute(text(EXPECTED),params).mappings()]
                actual=fetch(pid,params['cap'],params['seq'])
                actual_rows=[{k:r[k] for k in ('path','value','unit','display_name')} for r in actual['tree']]
                ok=actual_rows==expected
                record['G18a']={'status':'PASS' if ok else 'FAIL','sql':EXPECTED,'choose_sql':CHOOSE,'params':params,'sql_count':len(expected),'api_tree_count':len(actual['tree']),'exact_rows_match':ok,'hex_exposed':actual['hex'] is not None,'hex_reason':actual['reason']}
                failed |= not ok
            cases=[]
            for row in db.execute(text(RESTRICTED),{'pid':pid}).mappings():
                actual=fetch(pid,row['capture_id'],row['seq'])
                ok=actual['hex'] is None and bool(actual['reason'])
                cases.append({**dict(row),'hex':actual['hex'] if actual['hex'] is None else '[UNEXPECTED CONTENT WITHHELD FROM REPORT]','reason':actual['reason'],'status':'PASS' if ok else 'FAIL'})
                failed |= not ok
            complete=len(cases)==4
            record['G18b']={'status':'PASS' if complete and all(c['status']=='PASS' for c in cases) else 'FAIL','sql':RESTRICTED,'params':{'pid':pid},'cases':cases}
            failed |= not complete
            safe=db.execute(text(SAFE),{'pid':pid}).mappings().first()
            if safe:
                actual=fetch(pid,safe['capture_id'],safe['seq'])
                record['safe_payload']={'sql':SAFE,'params':{'pid':pid},**dict(safe),'hex_present':actual['hex'] is not None,'size_bytes':actual['size_bytes'],'reason':actual['reason']}
            report['projects'].append(record)
    if client:
        schema=client.get('/openapi.json');schema.raise_for_status()
        route=schema.json()['paths']['/projects/{project_id}/signaling/message']['get']
        report['openapi']={'response':route['responses']['200'],'parameters':route['parameters']}
        noauth=httpx.get(str(client.base_url).rstrip('/')+'/projects/134af70a06eb/signaling/message',params={'capture_id':'TEST-missing','seq':1})
        absent=client.get('/projects/134af70a06eb/signaling/message',params={'capture_id':'TEST-missing','seq':1})
        report['http_guards']={'no_auth':noauth.status_code,'missing_event':absent.status_code}
        failed |= noauth.status_code != 401 or absent.status_code != 404
finally:
    if client: client.close()
report['verdict']='FAIL' if failed else 'PASS'
print(json.dumps(report,indent=2))
sys.exit(1 if failed else 0)
