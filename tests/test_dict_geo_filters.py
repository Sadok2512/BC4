"""Transactional temporary tables: no project/reference/measurement data is mutated."""
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
from app.dict.geo_filters import geographic_options
from app.dict.service_v2 import build_distribution
from app.routes.project_dict_v2 import router
from app.deps import get_current_user
from app.db import get_db


@pytest.fixture
def db():
    with engine.connect() as connection:
        transaction = connection.begin()
        for ddl in [
            "CREATE TEMP TABLE projects(id text primary key) ON COMMIT DROP",
            "CREATE TEMP TABLE measurement_points(project_id text,capture_id text,seq int,earfcn int,rat text,tech text,ecgi text,ecgi_source text) ON COMMIT DROP",
            "CREATE TEMP TABLE cell_ref(eci text,dor text,dr text,plaque text,arcep_zone text) ON COMMIT DROP",
            "CREATE TEMP TABLE stg_event(id bigint,project_id text,capture_id text,seq int,system text,freq text) ON COMMIT DROP",
            "CREATE TEMP TABLE param_occurrence(id bigint,project_id text,stg_event_id bigint,param_key text,display_name text,unit_converted text,origin text,choice_of text,discriminators jsonb,value text,value_converted text,operator text,band text) ON COMMIT DROP",
        ]:
            connection.execute(text(ddl))
        connection.execute(text("INSERT INTO projects VALUES ('p'),('other')"))
        connection.execute(text("""INSERT INTO measurement_points VALUES
            ('p','a',1,100,'LTE','LTE','cell-a','sib1_strict_capture_earfcn'),
            ('p','a',2,100,'LTE','LTE','cell-a','sib1_strict_capture_earfcn'),
            ('p','b',1,200,'LTE','LTE','cell-b','sib1_strict_capture_earfcn'),
            ('other','x',1,100,'LTE','LTE','cell-a','sib1_strict_capture_earfcn'),
            ('p','c',1,100,'LTE','LTE','cell-a','inferred')"""))
        connection.execute(text("""INSERT INTO cell_ref VALUES
            ('cell-a','Nord',NULL,'Plaque A','Zone 1'),
            ('cell-a','Nord',NULL,'Plaque A','Zone 1'),
            ('cell-b','Sud',NULL,'Plaque B','Zone 2')"""))
        connection.execute(text("""INSERT INTO stg_event VALUES
            (1,'p','a',11,'LTE','100'),(2,'p','a',12,'LTE','100'),
            (3,'p','b',11,'LTE','200'),(4,'p','x',11,'LTE','100'),
            (5,'p','a',13,'LTE','999'),(6,'p','c',11,'LTE','100')"""))
        connection.execute(text("""INSERT INTO param_occurrence
            SELECT id,'p',id,'param','Parameter','ms','network_config',NULL,NULL,
                   CASE WHEN id=3 THEN '2' ELSE '1' END,
                   CASE WHEN id=3 THEN '20' ELSE '10' END,
                   'Orange','B1' FROM stg_event"""))
        session = Session(bind=connection)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


def test_options_are_project_bound_and_deduplicated(db):
    dimensions = geographic_options(db, 'p')['geographic']
    assert [d['count'] for d in dimensions] == [2, 2, 2]
    assert dimensions[0]['options'] == ['Nord', 'Sud']
    assert all(not d['available'] and d['reason'] for d in geographic_options(db, 'missing')['geographic'])


def test_intersection_and_no_count_multiplication(db):
    original = build_distribution(db, 'p', ['param'], 'operator')['blocks'][0]
    filtered = build_distribution(db, 'p', ['param'], 'operator', geographic={'dor': ('Nord',), 'plaque': ('Plaque A',), 'arcep_zone': ('Zone 1',)})['blocks'][0]
    assert original['n_total'] == 6
    assert filtered['n_total'] == 2
    assert filtered['distinct_values'] == 1
    assert filtered['values'][0]['value_display'] == '10 ms'
    assert filtered['values'][0]['groups'][0]['n'] == 2
    assert filtered['verdict'] == 'IDENTIQUE'
    assert filtered['source_result_id'] == original['result_id']
    assert filtered['result_id'] != original['result_id']
    assert build_distribution(db, 'p', ['param'], 'operator')['blocks'][0] == original


def test_multiselect_or_and_mismatched_dimensions(db):
    union = build_distribution(db, 'p', ['param'], 'band', geographic={'dor': ('Sud', 'Nord')})['blocks'][0]
    assert union['n_total'] == 3
    assert union['verdict'] == 'DIFFERENT'
    empty = build_distribution(db, 'p', ['param'], 'operator_band', geographic={'dor': ('Nord',), 'plaque': ('Plaque B',)})['blocks'][0]
    assert empty['n_total'] == 0 and empty['values'] == []
    assert empty['verdict'] == 'NON_COMPARE'


def test_ambiguous_ecgi_and_non_strict_sources_are_excluded(db):
    db.execute(text("INSERT INTO measurement_points VALUES ('p','a',3,100,'LTE','LTE','cell-b','sib1_strict_capture_earfcn')"))
    assert geographic_options(db, 'p')['geographic'][0]['options'] == ['Sud']
    with pytest.raises(HTTPException) as error:
        build_distribution(db, 'p', ['param'], 'operator', geographic={'dor': ('Nord',)})
    assert error.value.status_code == 422


def test_unavailable_filter_is_explicit(db):
    db.execute(text('DELETE FROM measurement_points'))
    with pytest.raises(HTTPException) as error:
        build_distribution(db, 'p', ['param'], 'operator', geographic={'dor': ('Nord',)})
    assert error.value.detail['code'] == 'GEOGRAPHIC_FILTER_UNAVAILABLE'


def test_api_repeated_query_parameters_and_auth(db, monkeypatch):
    # Require project lookup is tested separately by production route dependencies.
    import app.routes.project_dict_v2 as routes
    monkeypatch.setattr(routes, '_require_project', lambda session, pid: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: object()
    with TestClient(app) as client:
        response = client.get('/projects/p/dict/v2/filters')
        assert response.status_code == 200
        assert response.json()['geographic'][0]['available']
        response = client.get('/projects/p/dict/v2/distribution', params=[('keys','param'),('dor','Nord'),('dor','Sud')])
        assert response.status_code == 200, response.text
        assert response.json()['blocks'][0]['n_total'] == 3
        assert client.get('/projects/p/dict/v2/distribution?keys=param&dor=unknown').status_code == 422
        app.dependency_overrides.pop(get_current_user)
        assert client.get('/projects/p/dict/v2/filters').status_code == 401
