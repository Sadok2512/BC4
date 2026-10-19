"""Preview data migration and guards; always rollback, including on assertion failure."""
import json,runpy,datetime
from pathlib import Path
from sqlalchemy import text
from app.db import engine
from app.dict.migrate_v23 import upgrade_data,downgrade_data
q="""SELECT project_id,count(*) rows,bit_xor(hashtextextended(jsonb_build_array(id,stg_event_id,path,value,value_converted,param_key,discriminators)::text,0)) content_hash,bit_xor(hashtextextended(jsonb_build_array(id,is_identifier)::text,0)) flags_hash FROM param_occurrence WHERE project_id IN ('134af70a06eb','4b7bfd50ddb6') GROUP BY project_id ORDER BY project_id"""
with engine.connect() as c:
 tx=c.begin()
 try:
  before=[dict(r) for r in c.execute(text(q)).mappings()]
  upgrade_data(c)
  after=[dict(r) for r in c.execute(text(q)).mappings()]
  assert [(r['rows'],r['content_hash']) for r in before]==[(r['rows'],r['content_hash']) for r in after]
  export=runpy.run_path('audit/dict-v2.3/export_populations.py')['export']
  for pid in ('134af70a06eb','4b7bfd50ddb6'):export(c,pid)
  downgrade_data(c)
  restored=[dict(r) for r in c.execute(text(q)).mappings()]
  assert before==restored
  Path('audit/dict-v2.3/migration-check.json').write_text(json.dumps(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sql=q,before=before,after=after,restored=restored,status='PASS',persistent_mutations=False),indent=2)+'\n')
 finally:tx.rollback()
