"""Synthetic data stays in transaction-local pg_temp tables, never references."""
from sqlalchemy import text
from app.db import engine
from app.services.metric_samples import populate_metric_samples

def test_proof_registry_empty_then_explicit_extraction_is_scoped_idempotent():
    with engine.connect() as db:
        db.execute(text('CREATE TEMP TABLE metric_def(code text,event_code text,field_index integer,scale numeric,tech text) ON COMMIT DROP'))
        db.execute(text('CREATE TEMP TABLE stg_event_raw(id bigint,project_id text,capture_id text,seq integer,event_code text,system text,raw_fields jsonb) ON COMMIT DROP'))
        db.execute(text('CREATE TEMP TABLE metric_sample(project_id text,capture_id text,seq integer,metric_code text,raw_event_id bigint,raw_value text,value double precision,PRIMARY KEY(project_id,capture_id,seq,metric_code)) ON COMMIT DROP'))
        assert populate_metric_samples(db,'TEST-metrics')['definitions']==0
        db.execute(text("INSERT INTO metric_def VALUES ('test_only','PHRATE',4,0.5,'LTE')"))
        db.execute(text('''INSERT INTO stg_event_raw VALUES
          (1,'TEST-metrics','TEST-capture',1,'PHRATE','LTE','{"c4":"10"}'),
          (2,'TEST-metrics','TEST-capture',2,'PHRATE','LTE','{"c4": null}'),
          (3,'TEST-other','TEST-capture',3,'PHRATE','LTE','{"c4":"20"}'),
          (4,'TEST-metrics','TEST-capture',4,'PHRATE','NR','{"c4":"30"}')'''))
        for _ in range(2):
            assert populate_metric_samples(db,'TEST-metrics')['written']==1
            assert db.execute(text('SELECT seq,raw_value,value FROM metric_sample')).all()==[(1,'10',5.0)]
        db.rollback()
