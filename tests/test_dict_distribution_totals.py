"""Explicit population totals, including missing values, without source mutations."""
from sqlalchemy import text
from tests.test_dict_templates import db
from app.dict.service_v2 import build_distribution
from app.schemas.dict_v2 import DictDistributionResponse


def test_totals_are_sql_population_not_displayed_values(db, monkeypatch):
    monkeypatch.setattr('app.dict.service_v2.build_group_by_options', lambda *args: [])
    for value, op, band, tech in [('1','TEST-A','TEST-B1','LTE'),('2','TEST-A','TEST-B1','LTE'),(None,'TEST-A','TEST-B1','LTE'),('1','TEST-A','TEST-B2','LTE'),('1','TEST-B','TEST-B1','LTE'),('9','TEST-A','TEST-B1','NR')]:
        db.execute(text("""INSERT INTO param_occurrence(project_id,param_key,display_name,origin,value,operator,band,system) VALUES ('TEST','TEST/key','TEST-name','network_config',:v,:op,:band,:tech)"""),dict(v=value,op=op,band=band,tech=tech))
    for mode in ['operator','band','operator_band']:
        block=DictDistributionResponse(**build_distribution(db,'TEST',['TEST/key'],mode,technology='LTE')).blocks[0]
        assert sum(g.n for g in block.group_totals)==5
        assert sum(g.n for v in block.values for g in v.groups)==4
        if mode=='operator':
            assert {g.operator:g.n for g in block.group_totals}=={'TEST-A':4,'TEST-B':1}
        if mode=='operator_band':
            assert {(g.operator,g.band):g.n for g in block.group_totals}=={('TEST-A','TEST-B1'):3,('TEST-A','TEST-B2'):1,('TEST-B','TEST-B1'):1}
    assert build_distribution(db,'TEST',['TEST/absent'],'operator')['blocks'][0]['values']==[]
