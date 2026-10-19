import subprocess,sys,json,datetime
from pathlib import Path
from urllib.parse import urlencode
token=sys.stdin.read().strip();assert token
out=Path('/tmp/bc4-phase2-live');base='http://localhost:8000';pid='4b7bfd50ddb6'
records=[]
def call(name,path,expected=200):
 url=base+path
 proc=subprocess.run(['curl','--silent','--show-error','--write-out','\n%{http_code}','--config','-'],input='url = "'+url+'"\nheader = "Authorization: Bearer '+token+'"\n',text=True,capture_output=True,check=True)
 body,status=proc.stdout.rsplit('\n',1)
 assert int(status)==expected,(name,status,body[:150])
 data=json.loads(body)
 (out/(name+'.json')).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
 records.append(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),command='curl --silent --show-error '+url+' -H "Authorization: Bearer [REDACTED]"',status=int(status)))
 return data
listing=call('tasks','/projects/'+pid+'/tasks')
http_tasks=[t for t in listing['tasks'] if t['task_type']=='HTTP_DL']
task=next((t for t in http_tasks if t['status']=='ok'),http_tasks[0])
series=call('series-task','/projects/'+pid+'/kpi/THR_DL_APP/series?'+urlencode({'x':'task_time','task_id':task['id']}))
call('series-orange-lte','/projects/'+pid+'/kpi/THR_DL_APP/series?'+urlencode({'x':'task_time','operator':'Orange','tech':'LTE'}))
points=call('points-rsrp','/projects/'+pid+'/kpi/THR_DL_APP/points?x=rsrp&limit=5000')
(out/'points-rsrp-20-lines.txt').write_text('\n'.join((out/'points-rsrp.json').read_text().splitlines()[:20])+'\n')
call('result-admin','/results/'+series['result_id'])
call('axis-rejected','/projects/'+pid+'/kpi/THR_DL_APP/series?x=not_an_axis',422)
call('limit-rejected','/projects/'+pid+'/kpi/THR_DL_APP/points?x=rsrp&limit=5001',422)
call('cross-project-rejected','/projects/134af70a06eb/kpi/THR_DL_APP/series?'+urlencode({'x':'task_time','task_id':task['id']}),404)
(out/'curl-requests.json').write_text(json.dumps(records,indent=2)+'\n')
print(json.dumps({'tasks':len(listing['tasks']),'task_id':task['id'],'series_points':len(series['points']),'radio_points':len(points['points']),'result_id':series['result_id']}))
