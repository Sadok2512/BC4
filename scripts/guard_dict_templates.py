"""Manual G12a/b/c. Never mutates populated projects; creates only TEST-EMPTY via API."""
import argparse,json,os,subprocess,urllib.request
from collections import Counter
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('guard',choices=['G12a','G12b','G12c']);p.add_argument('--project',default='134af70a06eb');a=p.parse_args()
base=os.environ.get('BC4_API_BASE','http://localhost:8000')
def request(path,body=None):
    headers={'Content-Type':'application/json'}
    if 'token' in globals():headers['Authorization']='Bearer '+token
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
token=os.environ.get('BC4_TOKEN')
if not token:
    token=request('/auth/login',{'email':os.environ['BC4_ADMIN_EMAIL'],'password':os.environ['BC4_ADMIN_PASSWORD']})['token']
if a.guard=='G12a':
    sql="""WITH keys AS (SELECT DISTINCT system,param_key FROM param_occurrence WHERE project_id=:'pid' AND param_key IS NOT NULL), classified AS (SELECT k.*,coalesce((SELECT category_id FROM dict_category_map m WHERE m.technology=k.system AND (k.param_key=m.path_prefix OR starts_with(k.param_key,m.path_prefix||'/')) ORDER BY length(m.path_prefix) DESC LIMIT 1),'autres') category_id FROM keys k) SELECT param_key FROM keys EXCEPT SELECT param_key FROM classified c JOIN dict_category d ON d.id=c.category_id;"""
    # psql variable substitution is available on stdin, not -c.
    result=subprocess.run(['docker','exec','-i','bc4-db-1','psql','-U','bc4','-d','bc4','-X','-At','-v','ON_ERROR_STOP=1','-v','pid='+a.project],input=sql,text=True,capture_output=True,check=True)
    print('SQL:',sql);print(result.stdout,end='');assert not result.stdout.strip();print('G12a PASS: 0 uncovered keys')
elif a.guard=='G12b':
    from urllib.parse import urlencode
    summary=request(f'/projects/{a.project}/dict/v2/templates/drx/summary?group_by=operator')
    rows=[r for r in summary['rows'] if r['label']=='longDRX-Cycle' and r['resolved']]
    assert rows,'No verified longDRX-Cycle key'
    for row in rows:
        original=request(f'/projects/{a.project}/dict/v2/distribution?'+urlencode({'keys':row['param_key'],'group_by':'operator'}))['blocks'][0]
        def counts(values):
            c=Counter()
            for value in values:
                for group in value['groups']:c[(value['value'],group.get('operator'))]+=group['n']
            return c
        left,right=counts(row['distribution']),counts(original['values'])
        diff=[(str(k),left[k],right[k]) for k in left.keys()|right.keys() if left[k]!=right[k]]
        print(json.dumps({'param_key':row['param_key'],'summary_total':sum(left.values()),'distribution_total':sum(right.values()),'diff':diff}));assert not diff
    print('G12b PASS')
else:
    project=request('/projects',{'name':'TEST-EMPTY'})
    result=request(f"/projects/{project['id']}/dict/v2/templates")
    seed=json.loads(Path('app/dict/config/templates_v1.json').read_text())
    assert [c['id'] for c in result['categories']]==[c['id'] for c in seed['categories']]
    assert [[e['id'] for e in c['entries']] for c in result['categories']]==[[e['id'] for e in c['entries']] for c in seed['categories']]
    assert all(c['n_in_project']==0 and all(e['n_in_project']==0 for e in c['entries']) for c in result['categories'])
    print(json.dumps({'guard':'G12c','project_id':project['id'],'categories':len(result['categories']),'entries':sum(len(c['entries']) for c in result['categories']),'all_zero':True,'status':'PASS'}))
