"""Manual G13: SQL populations and service contract, no synthetic project data.
Run: python scripts/_guard_G13_categories.py [--preview] [project_id]
--preview runs the migration in a transaction and always rolls it back.
"""
import sys,json,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
from app.dict.catalog_v22 import ELIGIBLE,NORMALIZED
from app.dict.category_mapping import resolve_mapping
from app.dict.service_v2 import build_dict_tree,build_distribution
from app.schemas.dict_v2 import DictTreeResponse,DictDistributionResponse
pid=next((x for x in sys.argv[1:] if not x.startswith('--')),'134af70a06eb')
with engine.connect() as conn:
 tx=conn.begin()
 try:
  if '--preview' in sys.argv:
   from alembic.migration import MigrationContext
   from alembic.operations import Operations
   path=Path(__file__).resolve().parents[1]/'alembic/versions/0025_dict_categories_v22.py'
   spec=importlib.util.spec_from_file_location('migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
   migration.op=Operations(MigrationContext.configure(conn));migration.upgrade()
  db=Session(bind=conn)
  query=f"SELECT p.system,{NORMALIZED} path,p.param_key,p.discriminators,count(*) n FROM param_occurrence p WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE} GROUP BY 1,2,3,4"
  rows=list(db.execute(text(query),{'pid':pid}).mappings());maps=list(db.execute(text('SELECT * FROM dict_category_map')).mappings())
  keys=set();other=set();unmapped=[]
  for r in rows:
   k=(r['system'],r['param_key']);keys.add(k);m=resolve_mapping(r['system'],r['path'],r['discriminators'],maps)
   if not m or m['category_id']=='autres':other.add(k)
   if not m:unmapped.append(dict(r))
  print(json.dumps(dict(project_id=pid,guard='G13a',sql=query,parameters={'pid':pid},keys=len(keys),other=len(other),other_pct=100*len(other)/len(keys) if keys else None,status='PASS' if keys and len(other)/len(keys)<=.05 else 'FAIL',unmapped=unmapped),ensure_ascii=False,default=str))
  tree=DictTreeResponse(**build_dict_tree(db,pid,'catalog')).model_dump()
  leaves=[];nodes=[];total=0
  for tech in tree['tree']:
   for origin in tech['origins']:
    for cat in origin['categories']:
     for sub in cat['subcategories']:
      for node in sub['parameters']:
       nodes.append(node);leaves.extend(node['leaves']);total+=sum(l['n'] for l in node['leaves'])
    for msg in origin['messages']:
     for group in msg['groups']:total+=sum(l['n'] for l in group['kpis'])
  query2=f'SELECT count(*) FROM param_occurrence p WHERE p.project_id=:pid AND {ELIGIBLE}'
  expected=db.execute(text(query2),{'pid':pid}).scalar()
  print(json.dumps(dict(guard='G13b',sql=query2,parameters={'pid':pid},tree_leaf_sum=total,sql_total=expected,status='PASS' if total==expected else 'FAIL')))
  proof=[l for l in leaves if l['display_name'] in ('q-RxLevMin','timeToTrigger')]
  source_query=f"SELECT p.system,p.message,p.display_name,COALESCE(p.discriminators,'{{}}'::jsonb) discriminators,count(*) n FROM param_occurrence p WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE} AND p.display_name IN ('q-RxLevMin','timeToTrigger') GROUP BY 1,2,3,4"
  source=list(db.execute(text(source_query),{'pid':pid}).mappings())
  def population(rows):
   from collections import Counter
   c=Counter()
   for x in rows:c[(x['message'],x['display_name'],json.dumps(x['discriminators'] or {},sort_keys=True))]+=x['n']
   return c
  print(json.dumps(dict(guard='G13c',status='PASS' if population(source)==population(proof) and proof else 'FAIL',sql=source_query,parameters={'pid':pid},source=[dict(r) for r in source],leaves=proof),ensure_ascii=False))
  passed=True;details=[]
  for node in nodes:
   if node['display_name']!='timeToTrigger':continue
   result=DictDistributionResponse(**build_distribution(db,pid,[node['param_key']],'operator')).model_dump()['blocks'][0]
   expected=sum(l['n'] for l in node['leaves']);passed &= result['n_total']==expected
   details.append(dict(param_key=node['param_key'],expected=expected,result=result))
  print(json.dumps(dict(guard='G13d',status='PASS' if details and passed else 'FAIL',details=details),ensure_ascii=False))
 finally:
  tx.rollback()
