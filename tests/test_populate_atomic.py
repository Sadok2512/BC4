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
        parent=SimpleNamespace(refresh=lambda _:None, commit=lambda:None)
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


def test_parent_transaction_ends_before_long_population(monkeypatch):
    """Real PostgreSQL, read-only TEST2: old code exceeds the 200ms idle limit."""
    from sqlalchemy import event
    from app.models import Project
    with Session(engine) as parent:
        def short_timeout(session, transaction, connection):
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '200ms'"))
        event.listen(parent, 'after_begin', short_timeout)
        project = parent.get(Project, '134af70a06eb')
        if project is None:
            pytest.fail('TEST2 integration project absent')
        parent.commit()  # expires project.id, reproducing the worker call site
        def slow(work, stored):
            assert not parent.in_transaction()
            work.execute(text('SELECT pg_sleep(0.35)'))
            return {'test': 'long population completed'}
        monkeypatch.setattr(chain, '_run_populate_chain', slow)
        assert chain.run_populate_chain(parent, project)['test'] == 'long population completed'
        assert project.id == '134af70a06eb'
        parent.rollback()
