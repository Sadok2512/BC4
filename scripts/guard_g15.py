"""Manual live G15. Run inside API container (environment provides DSN/auth).
python scripts/guard_g15.py --out /tmp/g15
Evidence contains URLs, masked auth, timestamp, replayable SQL and raw curl.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import httpx
from sqlalchemy import text
from app.db import SessionLocal

parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
pid='134af70a06eb';cap='047e3f34e0af';other='fb5f59006096'
base=os.environ.get('BC4_API_BASE','http://localhost:8000')
client=httpx.Client(base_url=base,timeout=90)
auth=client.post('/auth/login',json={'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']});auth.raise_for_status();token=auth.json()['token']
client.headers['Authorization']='Bearer '+token
requests=[];sqls=[]
def get(path,name):
    response=client.get(path);response.raise_for_status();data=response.json()
    (out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    curl=subprocess.run(['curl','--silent','--show-error','--include','--config','-',base+path],input='header = "Authorization: Bearer '+token+'"\nheader = "Accept: application/json"\n',text=True,capture_output=True,check=True)
    (out/(name+'-curl.txt')).write_text(curl.stdout)
    requests.append({'url':base+path,'headers':{'Authorization':'Bearer <masked>','Accept':'application/json'},'at':datetime.now(timezone.utc).isoformat(),'status':response.status_code})
    return data

def sql(db,query,params):
    sqls.append({'sql':query,'params':params})
    return db.execute(text(query),params).all()

health=get('/health','health');assert health['version']=='0.55.0'
spec=get('/openapi.json','openapi')
for route in ['/projects/{project_id}/metrics','/projects/{project_id}/metrics/series','/projects/{project_id}/captures/{capture_id}/events']:
    assert spec['paths'][route]['get']['responses']['200']['content']['application/json']['schema']
catalog=get(f'/projects/{pid}/metrics','metrics')
assert next(m for m in catalog if m['code']=='pci')['source_table']=='stg_event_raw'
assert not {'ta','nr_arfcn','thr_ul'}&{m['code'] for m in catalog}
data=get(f'/projects/{pid}/metrics/series?capture_id={cap}&codes=rsrp,sinr,thr_dl,pci&max_points=100000','series')
with SessionLocal() as db:
    params={'pid':pid,'cap':cap}
    direct=sql(db,'SELECT seq,rsrp FROM measurement_points WHERE project_id=:pid AND capture_id=:cap AND rsrp IS NOT NULL ORDER BY seq',params)
    assert [(p['seq'],p['value']) for p in data['series'][0]['points']]==[tuple(r) for r in direct]
    assert all(a['t_rel_s']<=b['t_rel_s'] for s in data['series'] for a,b in zip(s['points'],s['points'][1:]))
    valid={r[0] for r in sql(db,'SELECT seq FROM stg_event_raw WHERE project_id=:pid AND capture_id=:cap',params)}
    assert data['capture_id']==cap and all(p['seq'] in valid for s in data['series'] for p in s['points'])
    events=get(f'/projects/{pid}/captures/{cap}/events?types=task,ho,rlf,rrc','events')
    tasks=sql(db,'SELECT seq_daa,seq_dcomp,task_type FROM task_run WHERE project_id=:pid AND capture_id=:cap',params)
    expected=sorted((seq,label+' · '+r.task_type) for r in tasks for seq,label in [(r.seq_daa,'DAA'),(r.seq_dcomp,'DCOMP')] if seq is not None)
    assert sorted((m['seq'],m['label']) for m in events['markers'] if m['type']=='task')==expected
    second=get(f'/projects/{pid}/metrics/series?capture_id={other}&codes=rsrp,pci','series-ho')
    direct_other=sql(db,'SELECT seq,rsrp FROM measurement_points WHERE project_id=:pid AND capture_id=:cap AND rsrp IS NOT NULL ORDER BY seq',{'pid':pid,'cap':other})
    assert second['capture_id']==other and [(p['seq'],p['value']) for p in second['series'][0]['points']]==[tuple(r) for r in direct_other]
    get(f'/projects/{pid}/captures/{other}/events?types=ho','events-ho')
    filtered=get(f'/projects/{pid}/metrics/captures?operator=Orange','captures-orange')
    direct_caps=sql(db,"SELECT DISTINCT capture_id FROM measurement_points WHERE project_id=:pid AND operator='Orange' AND capture_id IS NOT NULL ORDER BY capture_id",{'pid':pid})
    assert [r['capture_id'] for r in filtered]==[r[0] for r in direct_caps]
small=get(f'/projects/{pid}/metrics/series?capture_id={cap}&codes=rsrp&max_points=20','sampled')
repeat=client.get(f'/projects/{pid}/metrics/series?capture_id={cap}&codes=rsrp&max_points=20').json()
assert small['series']==repeat['series'] and small['series'][0]['n_returned']<=20
window=get(f'/projects/{pid}/metrics/series?capture_id={cap}&codes=rsrp&from_seq=1000&to_seq=5000','window')
assert all(1000<=p['seq']<=5000 for p in window['series'][0]['points'])
assert client.get(f'/projects/{pid}/metrics/series?capture_id={cap}&codes=sql_injection').status_code==422
assert client.get(f'/projects/{pid}/metrics/series?capture_id={cap},{other}&codes=rsrp').status_code==404
assert client.get(f'/projects/{pid}/metrics/series?capture_id=TEST-absent-capture&codes=rsrp').status_code==404
# Content-addressed capture IDs may legitimately occur in multiple projects.
with SessionLocal() as db:
    other_pid='4b7bfd50ddb6'
    direct_cross=sql(db,'SELECT seq,rsrp FROM measurement_points WHERE project_id=:pid AND capture_id=:cap AND rsrp IS NOT NULL ORDER BY seq',{'pid':other_pid,'cap':cap})
    cross=client.get(f'/projects/{other_pid}/metrics/series?capture_id={cap}&codes=rsrp').json()
    assert cross['project_id']==other_pid
    assert [(p['seq'],p['value']) for p in cross['series'][0]['points']]==[tuple(r) for r in direct_cross]
(out/'requests.json').write_text(json.dumps(requests,indent=2))
(out/'sql.json').write_text(json.dumps(sqls,indent=2))
summary={'G15a':'PASS diff vide (2 captures)','G15b':'PASS non décroissant, égalités conservées','G15c':'PASS capture unique, valeurs directes isolées, scope projet vérifié par SELECT direct','G15d':'PASS DAA/DCOMP exacts','sampling':'PASS déterministe <= max_points','window':'PASS','filtered_captures':'PASS SQL direct','version':health['version']}
(out/'guards.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
