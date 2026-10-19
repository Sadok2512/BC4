import os,json,datetime,httpx
base='http://127.0.0.1:8000'
with httpx.Client(timeout=120) as c:
 auth=c.post(base+'/auth/login',json={'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']});auth.raise_for_status()
 h={'Authorization':'Bearer '+auth.json()['token']}
 print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'health':c.get(base+'/health').json(),'headers':{'Authorization':'Bearer [REDACTED]'}}))
 for pid in ['134af70a06eb','4b7bfd50ddb6']:
  url=base+f'/projects/{pid}/dict/v2/tree?view=catalog'
  response=c.get(url,headers=h);response.raise_for_status()
  print('URL '+url)
  print('\n'.join(json.dumps(response.json(),ensure_ascii=False,indent=2).splitlines()[:200]))
