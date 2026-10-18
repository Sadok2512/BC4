import json
from pathlib import Path
import pytest
from sqlalchemy import text,event
from sqlalchemy.orm import Session
from app.db import engine
from app.dict.templates import classify,summarize,list_templates
from app.schemas.dict_templates import SummaryResponse,TemplatesResponse,TemplateUpdate

@pytest.fixture
def db():
    with engine.connect() as c:
        tx=c.begin()
        for ddl in [
            'CREATE TEMP TABLE dict_category(id text primary key,label text,position integer) ON COMMIT DROP',
            'CREATE TEMP TABLE dict_category_map(technology text,path_prefix text,category_id text) ON COMMIT DROP',
            'CREATE TEMP TABLE dict_template(category_id text,entries jsonb,revision integer default 1) ON COMMIT DROP',
            'CREATE TEMP TABLE param_occurrence(project_id text,param_key text,system text,discriminators jsonb,value text,value_converted text,unit_converted text,operator text,band text,is_identifier boolean) ON COMMIT DROP',
        ]:c.execute(text(ddl))
        data=json.loads(Path('app/dict/config/templates_v1.json').read_text())
        for cat in data['categories']:
            c.execute(text('INSERT INTO dict_category VALUES (:id,:label,:position)'),cat)
            c.execute(text('INSERT INTO dict_template(category_id,entries) VALUES (:id,CAST(:entries AS jsonb))'),dict(id=cat['id'],entries=json.dumps(cat['entries'])))
        session=Session(bind=c)
        yield session
        session.close();tx.rollback()

def test_exact_prefix():
    maps=[dict(technology='LTE',path_prefix='TEST/a',category_id='drx',label='DRX',position=9)]
    assert classify('LTE','TEST/a/x',maps)[0]=='drx'
    assert classify('LTE','TEST/alpha',maps)[0]=='autres'
    assert classify('NR','TEST/a',maps)[0]=='autres'

def test_empty_keeps_seed(db):
    result=TemplatesResponse(**list_templates(db,'TEST-EMPTY'))
    assert len(result.categories)==11
    assert sum(len(c.entries) for c in result.categories)==85
    assert all(e.n_in_project==0 for c in result.categories for e in c.entries)

def test_summary_population_null_ties_and_one_aggregate(db):
    key='TEST/path'
    entry=dict(id='drx-test',label='TEST-value',position=1,technology='LTE',discriminators={},parameters=[dict(param_key=key,technology='LTE',discriminators={'event':'A3'})],reason=None)
    db.execute(text("UPDATE dict_template SET entries=CAST(:v AS jsonb) WHERE category_id='drx'"),{'v':json.dumps([entry])})
    for pid,disc,value,op,band in [('TEST','A3','1','TEST-A','TEST-B'),('TEST','A3','1','TEST-A','TEST-B'),('TEST','A3',None,None,None),('OTHER','A3','99','TEST-A','TEST-B'),('TEST','A2','99','TEST-A','TEST-B')]:
        db.execute(text('INSERT INTO param_occurrence VALUES (:pid,:key,\'LTE\',CAST(:d AS jsonb),:v,NULL,NULL,:op,:band,false)'),dict(pid=pid,key=key,d=json.dumps({'event':disc}),v=value,op=op,band=band))
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(db.bind,'before_cursor_execute',capture)
    try:r=SummaryResponse(**summarize(db,'TEST','drx','operator'))
    finally:event.remove(db.bind,'before_cursor_execute',capture)
    assert len([s for s in statements if 'JOIN param_occurrence' in s])==1
    row=r.rows[0];assert row.n_in_project==3
    assert row.distribution[0].groups[0].n==2
    assert row.cells[0].dominant_value is None or row.cells[0].dominant_value=='1'
    missing=next(c for c in row.cells if c.operator is None)
    assert missing.n==1 and missing.missing_value_n==1 and missing.percentage is None
    assert next(c for c in row.cells if c.operator=='TEST-A').percentage==100

def test_admin_config_rejects_project_injection():
    with pytest.raises(ValueError):TemplateUpdate(revision=1,entries=[],project_id='OTHER')

def test_admin_permissions_revision_and_update(db):
    from fastapi import HTTPException
    from app.routes.settings_dict_templates import update_template
    from app.schemas.settings import Actor
    body=TemplateUpdate(revision=1,entries=[])
    with pytest.raises(HTTPException) as denied:
        update_template('drx',body,Actor(login='TEST-reader',role='viewer'),db)
    assert denied.value.status_code==403
    with pytest.raises(HTTPException) as stale:
        update_template('drx',TemplateUpdate(revision=999,entries=[]),Actor(login='TEST-admin',role='admin'),db)
    assert stale.value.status_code==409
    result=update_template('drx',body,Actor(login='TEST-admin',role='admin'),db)
    assert result.revision==2
