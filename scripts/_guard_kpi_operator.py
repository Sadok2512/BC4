"""Manual integration guard, real TEST2 API/SQL. Run with BC4 test deployment env."""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.db import SessionLocal
from app.nmf_decoder.projection import source_sql

out=Path(os.environ.get('BC4_GUARD_OUT','/tmp/kpi-operator-guard.json'))
pid='134af70a06eb'; cap='705aa521e9e0'; mixed='047e3f34e0af'
report={'at':datetime.now(timezone.utc).isoformat(),'project_id':pid,'requests':[],'sql':[],'checks':[]}
client=TestClient(app)
login=client.post('/auth/login',json={'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']});login.raise_for_status()
headers={'Authorization':'Bearer '+login.json()['token']}
def get(path,params=(),status=200):
 r=client.get(path,params=params,headers=headers)
 report['requests'].append({'url':str(r.url),'headers':{'Authorization':'Bearer admin (omitted)'},'status':r.status_code,'body':r.json()})
 assert r.status_code==status,(r.status_code,r.text[:1000])
 return r.json()
def sql(db,q,p):
 report['sql'].append({'sql':q,'params':p})
 return [dict(r) for r in db.execute(text(q),p).mappings()]
def passed(name):report['checks'].append({'name':name,'status':'PASS'});print('PASS',name,flush=True)
try:
 with SessionLocal() as db:
  cases={'all':[], 'orange':[('operator','Orange')], 'orange_sfr':[('operator','Orange'),('operator','SFR')], 'empty':[('operator_mode','none')]}
  # This capture's proven file attribution is checked, never assumed from its id.
  attribution=sql(db,"SELECT DISTINCT n.dl FROM stg_event_raw r JOIN nmf_file n ON n.id=r.nmf_file_id WHERE r.project_id=:pid AND r.capture_id=:cap",{'pid':pid,'cap':cap})
  from app.measure.mapping import operator_from_dl
  assert attribution and all(operator_from_dl(r['dl'])=='Orange' for r in attribution)
  datasets={}
  for name,ops in cases.items():
   args=[('capture_id',cap),('codes','rsrp,pdsch_bler,mac_dl_bler,sinr,thr_dl'),('max_points','100000'),*ops]
   data=get(f'/projects/{pid}/metrics/series',args);datasets[name]=data
   assert data['capture_id']==cap and data['result_id']
   for metric in data['series']:assert metric['n_returned']==len(metric['points'])
   markers=get(f'/projects/{pid}/captures/{cap}/events',ops)
   if name=='empty':assert all(not s['points'] for s in data['series']) and not markers['markers']
   for group in ['none','operator','operator_band']:
    detail=get(f'/projects/{pid}/kpi/LTE_DL_BLER',[('capture_id',cap),('group_by',group),*ops])
    assert detail['result_id']
    assert all(g.get('n',0)>0 for g in detail.get('groups') or [])
    if name=='empty':assert not detail.get('n') and not detail.get('groups')
    elif group!='none':assert all(g.get('operator')=='Orange' for g in detail['groups'])
   passed(name+' series/events/histogram/group population')
  for name in ['orange','orange_sfr']:
   assert datasets[name]['series']==datasets['all']['series']
  passed('union does not duplicate observations; All preserves file-proven capture')
  for metric in datasets['all']['series']:
   code={'rsrp':'cell_rsrp','sinr':'ci_rs_snr','thr_dl':'app_dl_bitrate'}.get(metric['code'],metric['code'])
   divisor=1e6 if metric['unit']=='Mbit/s' else 1
   rows=sql(db,'SELECT seq,value FROM ('+source_sql(code)+') s WHERE capture_id=:cap ORDER BY seq',{'pid':pid,'cap':cap})
   assert [(r['seq'],float(r['value'])/divisor) for r in rows]==[(p['seq'],p['value']) for p in metric['points']]
  passed('unfiltered values exactly match direct decoded SQL')
  # Mixed capture: check raw radio rows against their already stored attribution.
  mixed_data=get(f'/projects/{pid}/metrics/series',[('capture_id',mixed),('codes','rsrp'),('operator','Orange')])
  rows=sql(db,"SELECT DISTINCT seq,rsrp FROM measurement_points WHERE project_id=:pid AND capture_id=:cap AND operator='Orange' AND rsrp IS NOT NULL ORDER BY seq",{'pid':pid,'cap':mixed})
  assert [(r['seq'],r['rsrp']) for r in rows]==[(p['seq'],p['value']) for p in mixed_data['series'][0]['points']]
  passed('mixed capture: Orange RSRP matches independently attributed measurement_points')
  empty=get(f'/projects/{pid}/tasks',[('capture_id',cap),('operator_mode','none')]);assert not empty['tasks']
  get(f'/projects/{pid}/metrics/series',[('capture_id',cap),('codes','rsrp'),('operator','TEST-invalid')],422)
  passed('explicit empty tasks; unknown operator rejected')
  # RRC counters: global and groups derive from distinct admissible event ids.
  q="SELECT count(DISTINCT p.stg_event_id) n FROM param_occurrence p JOIN stg_event e ON e.id=p.stg_event_id AND e.project_id=p.project_id WHERE p.project_id=:pid AND e.capture_id=:cap AND p.operator=ANY(:ops) AND p.message='RRCConnectionRequest'"
  expected=sql(db,q,{'pid':pid,'cap':cap,'ops':['Orange','SFR']})[0]['n']
  counter=get(f'/projects/{pid}/kpi/LTE_RRC_ATTEMPTS',[('capture_id',cap),('operator','Orange'),('operator','SFR'),('group_by','none')])
  assert (counter.get('n') or 0)==expected
  passed('RRC count distinct SQL agrees; no synthetic timeline')
 report['status']='PASS'
except Exception as exc:
 report['status']='FAIL';report['error']=repr(exc);raise
finally:
 out.write_text(json.dumps(report,indent=2,default=str))
