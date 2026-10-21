"""Guard closed selectors and numerical/population semantics, no fabricated reference data."""
import pytest
from fastapi import HTTPException
from app.kpi.metrics_v3 import definitions,parse_selection,aggregate_values,percentile,Dataset

def test_closed_selectors_and_unproven_cells():
    d=definitions()
    assert parse_selection('plaid_mcs0@2',d)['cell']=='2'
    assert parse_selection('evt_RRD~rrd_rrc_rel_cause',d)['kind']=='categorical'
    assert not d['cell_rsrp']['cell_scoped']
    for token in ['cell_rsrp@1','plaid_mcs0@10','evt_CAA~caa_phone_number','evt_SEI~sei_m_tmsi','unk_CAA','rsrp; DROP TABLE capture']:
        with pytest.raises(HTTPException) as error:parse_selection(token,d)
        assert error.value.status_code==422

def test_last_is_ordered_and_null_is_not_zero():
    assert aggregate_values([{'value':None}],'mean') is None
    assert aggregate_values([{'value':2},{'value':0}],'last')==0
    assert percentile([0,10,100],.5)==10
    assert percentile([], .5) is None

def test_event_attributes_exclude_private_columns_and_keep_two_ho_durations():
    d=definitions();attrs={a['code'] for a in d['evt_HOI']['attributes']}
    assert {'ho_duration_nemo_ms','ho_duration_hoi_ms'}<=attrs
    assert not {'caa_phone_number','caa_own_phone_number'}&{a['code'] for a in d['evt_CAA']['attributes']}
    assert any(a.get('repeated') for a in d['evt_LOCK']['attributes'])

def test_explicit_empty_operator_population_is_not_all():
    ds=Dataset.__new__(Dataset);ds.lo=None;ds.hi=None;ds.allowed=set()
    assert not ds.admissible(1)
    ds.allowed=None;assert ds.admissible(1)
    ds.lo=2;assert not ds.admissible(1)
