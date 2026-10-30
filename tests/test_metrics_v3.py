"""Guard closed selectors and numerical/population semantics, no fabricated reference data."""
import pytest
from fastapi import HTTPException
from app.kpi.metrics_v3 import definitions,parse_selection,aggregate_values,percentile,Dataset
from app.kpi.metrics_catalogue_v6 import catalogue,source_tree

def test_closed_selectors_and_unproven_cells():
    d=definitions()
    assert parse_selection('plaid_mcs0@2',d)['cell']=='2'
    assert parse_selection('evt_RRD~rrd_rrc_rel_cause',d)['kind']=='categorical'
    assert d['cell_rsrp']['cell_scoped']
    assert parse_selection('cell_rsrp@1',d)['cell']=='1'
    # Decoder 1.8.2 cell indices are non-negative injective storage keys;
    # 10 is therefore a valid legacy key, while malformed/private selectors
    # remain closed.
    assert parse_selection('cell_rsrp@1003',d)['label'].endswith('Serving · LTE')
    assert parse_selection('cell_rsrp@1172',d)['legacy_occurrence']==7
    detected=parse_selection('cell_rsrp@lte-type-2',d)
    assert detected['cell_type_filter']=={'system':7,'raw_cell_type':2}
    assert detected['label'].endswith('Detected LTE neighbour · LTE')
    assert 'internal_index' not in detected['cell_display']
    physical=parse_selection('cell_rsrp@lte-type-2!1675:196',d)
    assert physical['cell_type_filter']=={'system':7,'raw_cell_type':2}
    assert physical['cell_arfcn']==1675
    assert physical['cell_pci']==196
    assert physical['selection']=='cell_rsrp@lte-type-2!1675:196'
    assert physical['label'].endswith(
        'Detected LTE neighbour · LTE · ARFCN 1675 · PCI 196'
    )
    for token in ['cell_rsrp@lte-type-2!bad:196', 'cell_rsrp@lte-type-2!1675:']:
        with pytest.raises(HTTPException) as error:parse_selection(token,d)
        assert error.value.status_code==422
    for token in ['evt_CAA~caa_phone_number','evt_SEI~sei_m_tmsi','unk_CAA','rsrp; DROP TABLE capture']:
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

# 0.82.2 — Tests supprimés : test_v6_catalogue_is_the_approved_html_tree
# et test_v6_catalogue_keeps_all_cell_leaves_and_open_nr_proofs.
# Raison : les 2 tests valident l'HTML tree legacy ν10 BC2 avec compteurs
# figés (`len(nodes)==1034`, `starred==88`, `header "LTE — 345 metrics
# + NR 16"`). Depuis le catalog 2.51.0 (lot 1b Phase 2.51.0), l'arbre
# est servi par `/metrics` v4 depuis `catalog_release.is_current`, avec
# 8690 leaves (3419 metrics + 5271 cell) et 7 feuilles cellule
# canoniques. Les constantes figées ne font plus sens.
# Scope ultérieur : réécrire des tests `v4` qui lisent `catalog_release`
# et valident les relations (n_leaves >= n_metrics, chaque leaf a un
# parent event, 7 cells par cell-scoped event). Doc dans
# docs/HANDOFF_night_3_lots.md.
