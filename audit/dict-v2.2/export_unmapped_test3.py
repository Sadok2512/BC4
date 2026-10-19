"""Read-only live audit. Run from repository root with application DB environment."""
import csv,json,datetime
from pathlib import Path
from sqlalchemy import text
from app.db import engine
from app.dict.catalog_v22 import NORMALIZED,ELIGIBLE
from app.dict.category_mapping import resolve_mapping
out=Path('audit/dict-v2.2')
def save(name,obj): (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n')
with engine.connect() as db:
 q=f"SELECT p.system technology,p.message,{NORMALIZED} path,p.param_key,COALESCE(p.discriminators,'{{}}'::jsonb) discriminator,count(*) n_occurrences FROM param_occurrence p WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE} GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5"
 rows=list(db.execute(text(q),{'pid':'4b7bfd50ddb6'}).mappings()); maps=list(db.execute(text('SELECT * FROM dict_category_map')).mappings())
 missing=[dict(r) for r in rows if resolve_mapping(r['technology'],r['path'],r['discriminator'],maps) is None]
 with Path('audit/dict-v2.2/unmapped_test3.csv').open('w') as f:
  fields=next(csv.reader(Path('audit/dict-v2.2/unmapped.csv').open()));w=csv.DictWriter(f,fields);w.writeheader()
  for i,r in enumerate(missing,1):
   r.update(discriminator=json.dumps(r['discriminator'],sort_keys=True),question='Quelle catégorie et sous-catégorie pour ce chemin et ce discriminant ?',category_id='',subcategory_id='',question_id=f'T3-{i:04d}');w.writerow(r)
 keys={(r['technology'],r['param_key']) for r in rows};unknown={(r['technology'],r['param_key']) for r in missing}
 save('unmapped_test3.source.json',dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_id='4b7bfd50ddb6',sql=q,parameters={'pid':'4b7bfd50ddb6'},mapping_sql='SELECT * FROM dict_category_map',keys=len(keys),unmapped_keys=len(unknown),csv_rows=len(missing),status='FAIL',mapping_mutations=0))
