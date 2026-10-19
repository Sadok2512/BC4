"""Read SQL populations inside the guard transaction, after reviewed data migration."""
import csv,json,datetime
from pathlib import Path
from sqlalchemy import text
from app.dict.catalog_v22 import NORMALIZED,ELIGIBLE
from app.dict.category_mapping import resolve_mapping,identifier_path_rule,excluded_field

def export(db,pid):
 out=Path('audit/dict-v2.3')
 q=f"SELECT p.system technology,p.message,{NORMALIZED} path,p.param_key,p.is_identifier,COALESCE(p.discriminators,'{{}}'::jsonb) discriminator,count(*) n_occurrences FROM param_occurrence p WHERE p.project_id=:pid GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,6"
 rows=list(db.execute(text(q),{'pid':pid}).mappings())
 fields=['project_id','technology','message','path','param_key','discriminator','n_occurrences','rule']
 with (out/f'excluded-{pid}.csv').open('w') as f:
  w=csv.DictWriter(f,fields);w.writeheader()
  for r in rows:
   if not excluded_field(r['path'],r['is_identifier']):continue
   rule=identifier_path_rule(r['path']) or ('existing is_identifier=true' if r['is_identifier'] else 'approved padding / systemFrameNumber exclusion')
   w.writerow(dict(project_id=pid,**{k:r[k] for k in ['technology','message','path','param_key','n_occurrences']},discriminator=json.dumps(r['discriminator'],sort_keys=True),rule=rule))
 q2=f"SELECT p.system technology,p.message,{NORMALIZED} path,p.param_key,COALESCE(p.discriminators,'{{}}'::jsonb) discriminator,count(*) n_occurrences FROM param_occurrence p WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE} GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5"
 maps=list(db.execute(text('SELECT * FROM dict_category_map')).mappings());unknown=[]
 for r in db.execute(text(q2),{'pid':pid}).mappings():
  if resolve_mapping(r['technology'],r['path'],r['discriminator'],maps) is None:unknown.append(dict(r))
 with (out/f'unmapped-{pid}.csv').open('w') as f:
  fields=['technology','message','path','param_key','discriminator','n_occurrences','question','category_id','subcategory_id','question_id'];w=csv.DictWriter(f,fields);w.writeheader()
  for i,r in enumerate(unknown,1):w.writerow(dict(r,discriminator=json.dumps(r['discriminator'],sort_keys=True),question='Quelle catégorie et sous-catégorie pour ce contexte ASN.1 ?',question_id=f'RESIDUAL-{i:04d}'))
 (out/f'population-source-{pid}.json').write_text(json.dumps(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_id=pid,parameters={'pid':pid},excluded_sql=q,eligible_sql=q2,mapping_sql='SELECT * FROM dict_category_map',unknown_populations=len(unknown)),indent=2)+'\n')
