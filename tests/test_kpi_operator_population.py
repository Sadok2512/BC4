from app.kpi.population import predicate, source_predicate
from app.routes.tasks import where


def test_no_selection_is_explicit_false_not_unrestricted():
    assert predicate({}) == ('TRUE', {})
    assert predicate({'operator_mode':'none'}) == ('FALSE', {})
    assert 'FALSE' in where('TEST-project',{'operator_mode':'none'})[0]


def test_values_are_bound_and_multiple_operators_form_one_population():
    cond,params=predicate({'operator':['TEST-A',"TEST-B' OR TRUE"],'band':['TEST-band']})
    assert "TEST-B" not in cond
    assert params['filter_operator']==['TEST-A',"TEST-B' OR TRUE"]
    assert 'ANY(:filter_operator)' in cond and 'ANY(:filter_band)' in cond


def test_capture_scopes_rrc_by_event_identity_not_time():
    sql,params=source_predicate('param_occurrence',{'capture_id':'TEST-cap','operator':['TEST-op']})
    assert 'e.id=param_occurrence.stg_event_id' in sql and 'e.capture_id=:filter_capture_id' in sql
    assert params['filter_capture_id']=='TEST-cap' and ' ts' not in sql


def test_transfer_catalogue_availability_does_not_require_applied_filters():
    from types import SimpleNamespace
    from app.kpi.service_v2 import compute_status_v2
    status = compute_status_v2(
        None, 'TEST-project',
        {'available_check': {'kind': 'transfers_table', 'arg': 'dl'}},
        transfers_cache=[SimpleNamespace(verdict='proven', direction='dl', thrpt_mbps=1)],
    )
    assert status.status == 'AVAILABLE'


def test_unassigned_selection_is_null_population_not_all():
    assert 'c.operator IS NULL' in predicate({'operator':['N/D']})[0]
    assert 'param_occurrence.operator IS NULL' in source_predicate('param_occurrence',{'operator':['N/D']})[0]
    assert 't.operator IS NULL' in where('TEST-project',{'operator':['N/D']})[0]
    assert 'IS NULL' not in predicate({'operator':['TEST-op']})[0]
