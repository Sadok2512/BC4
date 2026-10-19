"""Data migration operations for user-approved IE rules; no KPI or reference writes."""
import json
from pathlib import Path
from sqlalchemy import text
from app.dict.category_mapping import identifier_path_rule

FLAG_PATHS_SQL = 'SELECT DISTINCT path FROM param_occurrence'
FLAG_UPDATE_SQL = 'UPDATE param_occurrence SET is_identifier=:flag WHERE path IN (SELECT unnest(CAST(:paths AS text[]))) AND is_identifier IS DISTINCT FROM :flag'


def upgrade_data(db):
    seed=json.loads((Path(__file__).parent/'config/categories_v23.json').read_text())
    def backup(name,rows):
        db.execute(text('INSERT INTO dict_v22_backup(name,payload) VALUES (:name,CAST(:payload AS jsonb))'),{'name':'v23_'+name,'payload':json.dumps(rows,default=str)})
    backup('maps',[dict(r) for r in db.execute(text('SELECT * FROM dict_category_map')).mappings()])
    paths=list(db.execute(text(FLAG_PATHS_SQL)).scalars())
    identifiers=[p for p in paths if identifier_path_rule(p)]
    exceptions=[p for p in paths if p.rsplit('/',1)[-1]=='logicalChannelGroup']
    changed=[]
    for flag,selected in ((True,identifiers),(False,exceptions)):
        changed.extend(dict(r) for r in db.execute(text('SELECT id,is_identifier FROM param_occurrence WHERE path IN (SELECT unnest(CAST(:paths AS text[]))) AND is_identifier IS DISTINCT FROM :flag'),dict(paths=selected,flag=flag)).mappings())
    backup('flags',changed)
    backup('new_subcategories',[s['id'] for s in seed['subcategories']])
    for sub in seed['subcategories']:
        db.execute(text('INSERT INTO dict_subcategory(id,category_id,code,label,position) VALUES (:id,:category_id,:code,:label,:position)'),sub)
    db.execute(text('DELETE FROM dict_category_map'))
    for m in seed['maps']:
        db.execute(text('INSERT INTO dict_category_map(technology,path_prefix,category_id,subcategory_id,discriminator,note) VALUES (:technology,:path_prefix,:category_id,:subcategory_id,CAST(:discriminator AS jsonb),:note)'),dict(m,discriminator=json.dumps(m['discriminator'])))
    for flag,selected in ((True,identifiers),(False,exceptions)):
        db.execute(text(FLAG_UPDATE_SQL),dict(paths=selected,flag=flag))


def downgrade_data(db):
    backup={r['name'][4:]:r['payload'] for r in db.execute(text("SELECT * FROM dict_v22_backup WHERE name LIKE 'v23_%'")).mappings()}
    db.execute(text('DELETE FROM dict_category_map'))
    for m in backup['maps']:
        db.execute(text('INSERT INTO dict_category_map(id,technology,path_prefix,category_id,subcategory_id,discriminator,note) VALUES (:id,:technology,:path_prefix,:category_id,:subcategory_id,CAST(:discriminator AS jsonb),:note)'),dict(m,discriminator=json.dumps(m['discriminator'])))
    db.execute(text('UPDATE param_occurrence p SET is_identifier=f.is_identifier FROM jsonb_to_recordset(CAST(:flags AS jsonb)) AS f(id bigint,is_identifier boolean) WHERE p.id=f.id'), {'flags':json.dumps(backup['flags'])})
    db.execute(text('DELETE FROM dict_subcategory WHERE id=ANY(:ids)'),{'ids':backup['new_subcategories']})
    db.execute(text("DELETE FROM dict_v22_backup WHERE name LIKE 'v23_%'"))
