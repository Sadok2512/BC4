"""Fault-injection against PostgreSQL: legacy commits must not persist prefixes."""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
import app.db as database
import app.services.populate_chain as chain


def test_chain_rolls_back_internal_commits_on_failure(monkeypatch):
    with engine.connect() as conn:
        conn.execute(text('CREATE TEMP TABLE test_bc2_atomic(value integer)'));conn.commit()
        class BoundEngine:
            @contextmanager
            def begin(self):
                with conn.begin():yield conn
        monkeypatch.setattr(database,'engine',BoundEngine())
        project=SimpleNamespace(id='TEST-atomic-project')
        monkeypatch.setattr(Session,'get',lambda *args:project)
        def fail(work,project):
            work.execute(text('INSERT INTO test_bc2_atomic VALUES (1)'));work.commit()
            work.execute(text('INSERT INTO test_bc2_atomic VALUES (2)'));work.commit()
            raise RuntimeError('TEST interrupted after commits')
        monkeypatch.setattr(chain,'_run_populate_chain',fail)
        parent=SimpleNamespace(refresh=lambda _:None)
        with pytest.raises(RuntimeError,match='interrupted'):
            chain.run_populate_chain(parent,project)
        assert conn.execute(text('SELECT count(*) FROM test_bc2_atomic')).scalar()==0
        conn.rollback()


def test_chain_detects_unenriched_capture():
    from app.measure.cellmeas_repair import assert_lte_enriched
    class Result:
        def mappings(self):return self
        def all(self):return [dict(capture_id='TEST-missing',missing=2)]
    db=SimpleNamespace(execute=lambda *args:Result())
    with pytest.raises(RuntimeError,match='TEST-missing'):
        assert_lte_enriched(db,'TEST-project')
