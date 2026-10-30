from unittest.mock import MagicMock

from app.scripts import invalidate_catalog_cache as command


def _result(*, scalar=None, rowcount=0):
    result = MagicMock()
    result.scalar_one.return_value = scalar
    result.rowcount = rowcount
    return result


def test_invalidation_reports_rows_and_is_replay_safe():
    db = MagicMock()
    projects = _result()
    projects.scalars.return_value = ["p1", "p2"]
    replay_projects = _result()
    replay_projects.scalars.return_value = ["p1", "p2"]
    db.execute.side_effect = [projects, _result(scalar=2), _result(rowcount=2),
                              _result(scalar=2), replay_projects, _result(scalar=2),
                              _result(rowcount=2), _result(scalar=2)]
    rebuild = MagicMock()

    original = command._rebuild_project_cache
    command._rebuild_project_cache = rebuild
    try:
        first = command.invalidate_catalog_cache(db, reason="release", source="test")
        second = command.invalidate_catalog_cache(db, reason="replay", source="test")
    finally:
        command._rebuild_project_cache = original

    assert (first["rows_before"], first["rows_deleted"], first["rows_after"]) == (2, 2, 2)
    assert (second["rows_before"], second["rows_deleted"], second["rows_after"]) == (2, 2, 2)
    assert first["rows_rebuilt"] == second["rows_rebuilt"] == 2
    assert rebuild.call_count == 4
    assert first["idempotent"] is True
    assert second["idempotent"] is True


def test_command_refuses_without_bc3_lock_before_session(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(command, "guard_bc3_deploy_lock", lambda **_kwargs: False)
    monkeypatch.setattr(command, "SessionLocal", session)

    assert command.main(["--reason", "catalog release"]) == 1
    session.assert_not_called()


def test_command_requires_non_empty_reason(monkeypatch):
    guard = MagicMock()
    monkeypatch.setattr(command, "guard_bc3_deploy_lock", guard)

    assert command.main(["--reason", "   "]) == 2
    guard.assert_not_called()
