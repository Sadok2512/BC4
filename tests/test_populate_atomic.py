"""Fault-injection: slices are durable and a failed chain releases its lock."""
from types import SimpleNamespace
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import engine
import app.services.populate_chain as chain


def test_chain_keeps_committed_slice_and_releases_lock_on_failure(monkeypatch):
    project_id = '134af70a06eb'
    project = SimpleNamespace(id=project_id)
    monkeypatch.setattr(Session, 'get', lambda *args: project)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS test_bc1_slice_commit(value integer)'))
        conn.execute(text('TRUNCATE test_bc1_slice_commit'))
    try:
        def fail(work, project):
            work.execute(text('INSERT INTO test_bc1_slice_commit VALUES (1)'))
            work.commit()
            raise RuntimeError('TEST interrupted after slice commit')
        monkeypatch.setattr(chain, '_run_populate_chain', fail)
        parent = SimpleNamespace(refresh=lambda _: None, commit=lambda: None)
        with pytest.raises(RuntimeError, match='interrupted'):
            chain.run_populate_chain(parent, project)
        with engine.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM test_bc1_slice_commit')).scalar() == 1
            assert conn.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:k))"),
                {'k': 'populate:' + project_id},
            ).scalar() is True
            conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:k))"),
                {'k': 'populate:' + project_id},
            )
    finally:
        with engine.begin() as conn:
            conn.execute(text('DROP TABLE IF EXISTS test_bc1_slice_commit'))


def test_chain_detects_unenriched_capture():
    from app.measure.cellmeas_repair import assert_lte_enriched
    class Result:
        def mappings(self):return self
        def all(self):return [dict(capture_id='TEST-missing',missing=2)]
    db=SimpleNamespace(execute=lambda *args:Result())
    with pytest.raises(RuntimeError,match='TEST-missing'):
        assert_lte_enriched(db,'TEST-project')


def test_parent_transaction_ends_before_long_population(monkeypatch):
    """Le parent est clos avant le travail lent sur la connexion dédiée."""
    project = SimpleNamespace(id='TEST-parent-project')
    monkeypatch.setattr(Session, 'get', lambda *args: project)
    parent = SimpleNamespace(
        active=True,
        commit=lambda: setattr(parent, 'active', False),
        refresh=lambda _: None,
    )
    def slow(work, stored):
        assert parent.active is False
        work.execute(text('SELECT pg_sleep(0.35)'))
        work.commit()
        return {'test': 'long population completed'}
    monkeypatch.setattr(chain, '_run_populate_chain', slow)
    assert chain.run_populate_chain(parent, project)['test'] == 'long population completed'
