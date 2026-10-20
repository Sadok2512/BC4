"""Temporary-table integration tests; production project rows are never modified."""
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from tests.test_dict_geo_filters import db  # noqa: F401
from app.dict.map_v2 import build_map
from app.dict.service_v2 import build_distribution
from app.schemas.dict_v2 import DictMapResponse


@pytest.fixture
def mapped_db(db):
    for sql in [
        "ALTER TABLE stg_event ADD lat float, ADD lon float, ADD nmf_file_id text",
        "ALTER TABLE param_occurrence ADD system text DEFAULT 'LTE', ADD path text DEFAULT 'root/param'",
        "UPDATE stg_event SET lat=48.5,lon=2.5,nmf_file_id='file'",
        "UPDATE stg_event SET lat=NULL WHERE id=2",
        "UPDATE stg_event SET lat=100 WHERE id=4",
        "UPDATE stg_event SET project_id='other' WHERE id=5",
        "UPDATE param_occurrence SET operator=NULL,band=NULL WHERE id=6",
    ]:
        db.execute(text(sql))
    return db


def test_points_use_exact_event_source_and_no_site_coordinates(mapped_db):
    result = DictMapResponse(**build_map(mapped_db, 'p', ['param']))
    assert result.total_occurrences == 6
    assert result.geolocated_occurrences == 3
    assert [p.occurrence_id for p in result.points] == ['1', '3', '6']
    assert [(p.capture_id, p.seq) for p in result.points] == [('a', 11), ('b', 11), ('c', 11)]
    assert all(p.source and p.nmf_file_id == 'file' and p.coordinate_source == 'stg_event' for p in result.points)
    assert sum(o.count for o in result.operators) == 3


def test_operator_band_and_null_filters(mapped_db):
    result = build_map(mapped_db, 'p', ['param'], operators=['Orange'], bands=['B1'])
    assert result['total_occurrences'] == 5
    assert len(result['points']) == 2
    result = build_map(mapped_db, 'p', ['param'], operators=['N/D'], bands=['N/D'])
    assert [p['occurrence_id'] for p in result['points']] == ['6']
    assert result['operators'] == [{'name': 'N/D', 'count': 1, 'color': '#CBD5E1'}]


def test_geography_matches_distribution_and_does_not_multiply(mapped_db):
    geo = {'dor': ('Nord',)}
    result = build_map(mapped_db, 'p', ['param'], geographic=geo)
    distribution = build_distribution(mapped_db, 'p', ['param'], 'operator_band', geographic=geo)
    assert result['total_occurrences'] == distribution['blocks'][0]['n_total'] == 2
    assert [p['occurrence_id'] for p in result['points']] == ['1']
    assert result['points'][0]['lat'] == 48.5


def test_filters_technology_project_and_key(mapped_db):
    assert not build_map(mapped_db, 'p', ['param'], technology='NR')['points']
    assert not build_map(mapped_db, 'other', ['param'])['points']
    assert not build_map(mapped_db, 'p', ['unknown'])['points']
    distribution = build_distribution(mapped_db, 'p', ['param'], 'operator_band', technology='NR')
    assert distribution['blocks'][0]['n_total'] == 0


def test_limit_is_explicit_and_legend_counts_returned_population(mapped_db):
    result = build_map(mapped_db, 'p', ['param'], limit=1)
    assert result['truncated'] and result['geolocated_occurrences'] == 3
    assert result['returned_occurrences'] == 1
    assert sum(o['count'] for o in result['operators']) == 1


def test_zero_values_and_zero_coordinates_are_real(mapped_db):
    mapped_db.execute(text("UPDATE param_occurrence SET value='0',value_converted='0' WHERE id=1"))
    mapped_db.execute(text("UPDATE stg_event SET lat=0,lon=0 WHERE id=1"))
    point = build_map(mapped_db, 'p', ['param'])['points'][0]
    assert point['lat'] == point['lon'] == 0
    assert point['value_raw'] == point['value_converted'] == '0'


def test_unknown_geography_rejected(mapped_db):
    with pytest.raises(HTTPException) as error:
        build_map(mapped_db, 'p', ['param'], geographic={'dor': ('INVENTED',)})
    assert error.value.status_code == 422


def test_missing_values_and_ue_reports_not_in_map_population(mapped_db):
    mapped_db.execute(text("UPDATE param_occurrence SET value=NULL,value_converted=NULL WHERE id=1"))
    mapped_db.execute(text("UPDATE param_occurrence SET origin='ue_report' WHERE id=3"))
    assert [p['occurrence_id'] for p in build_map(mapped_db, 'p', ['param'])['points']] == ['6']


def test_map_api_query_contract_and_auth(mapped_db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.project_dict_v2 import router
    from app.deps import get_current_user
    from app.db import get_db
    import app.routes.project_dict_v2 as routes
    monkeypatch.setattr(routes, '_require_project', lambda session, pid: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: mapped_db
    app.dependency_overrides[get_current_user] = lambda: object()
    with TestClient(app) as client:
        response = client.get('/projects/p/dict/v2/map', params=[('keys','param'), ('operator','Orange'), ('operator','N/D'), ('dor','Nord')])
        assert response.status_code == 200, response.text
        assert response.json()['points'][0]['event_id'] == '1'
        for query in ['keys=', 'keys=param&limit=10001', 'keys=param&technology=WRONG', 'keys=param&dor=unknown']:
            assert client.get('/projects/p/dict/v2/map?' + query).status_code == 422
        app.dependency_overrides.pop(get_current_user)
        assert client.get('/projects/p/dict/v2/map?keys=param').status_code == 401


def test_aggregate_keys_resolve_source_occurrences_without_duplicates(mapped_db):
    from app.dict.catalog_v22 import selector_key
    mapped_db.execute(text("ALTER TABLE param_occurrence ADD is_identifier boolean DEFAULT false, ADD message text DEFAULT 'TEST-message'"))
    mapped_db.execute(text("CREATE TEMP TABLE dict_category_map(path_prefix text) ON COMMIT DROP"))
    identity = dict(tech='LTE', category='autres', subcategory=None, name='Parameter', unit='ms')
    parent = selector_key(identity)
    leaf = selector_key(dict(identity, message='TEST-message', discriminators={}))
    original = build_map(mapped_db, 'p', ['param'])
    for keys in [[parent], [leaf], [parent, leaf, 'param', parent]]:
        actual = build_map(mapped_db, 'p', keys)
        assert actual == original
    assert build_map(mapped_db, 'p', [parent], operators=['N/D'])['points'][0]['occurrence_id'] == '6'
    assert build_map(mapped_db, 'p', [parent], technology='NR')['points'] == []
    assert build_map(mapped_db, 'other', [parent])['points'] == []
    different = selector_key(dict(identity, name='TEST-absent'))
    assert build_map(mapped_db, 'p', [different])['points'] == []
    assert build_map(mapped_db, 'p', [different, parent]) == original


def test_malformed_aggregate_map_key_rejected(mapped_db):
    with pytest.raises(HTTPException) as error:
        build_map(mapped_db, 'p', ['dict22:invalid'])
    assert error.value.status_code == 422
