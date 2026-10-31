import json
from unittest.mock import MagicMock

import pytest

from scripts.catalog import bootstrap_catalog_release as bootstrap


def _catalog(tmp_path):
    path = tmp_path / "catalog_9.9.9.json"
    path.write_text(json.dumps({
        "spec_version": "2.50",
        "decoder_min_version": "1.8.2",
        "n_categories": 1,
        "n_metrics": 2,
        "n_leaves": 3,
    }), encoding="utf-8")
    return path


def _configure(monkeypatch, tmp_path, holder=None):
    catalog = _catalog(tmp_path)
    lock = tmp_path / "DEPLOY_LOCK"
    if holder is not None:
        lock.write_text(f"# BC4 DEPLOY LOCK\nholder: {holder}\n", encoding="utf-8")
    monkeypatch.setenv("BC4_DEPLOY_LOCK_PATH", str(lock))
    monkeypatch.setattr(bootstrap, "catalog_file_path", lambda _version: catalog)
    return lock


def test_activate_refuses_without_lock_and_opens_no_session(monkeypatch, tmp_path, capsys):
    _configure(monkeypatch, tmp_path)
    session = MagicMock()
    monkeypatch.setattr(bootstrap, "SessionLocal", session)

    assert bootstrap.main(["--version", "9.9.9", "--activate"]) == 1
    session.assert_not_called()
    assert "VERDICT=FAIL reason=deploy_lock_required" in capsys.readouterr().err


def test_activate_refuses_lock_held_by_another_and_opens_no_session(
    monkeypatch, tmp_path, capsys,
):
    _configure(monkeypatch, tmp_path, holder="BC3")
    session = MagicMock()
    monkeypatch.setattr(bootstrap, "SessionLocal", session)

    assert bootstrap.main(["--version", "9.9.9", "--activate"]) == 1
    session.assert_not_called()
    assert "holder autorise parmi BC1,BC4, holder=BC3" in capsys.readouterr().err


def test_prepare_default_and_explicit_open_no_database_session(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    session = MagicMock()
    monkeypatch.setattr(bootstrap, "SessionLocal", session)

    assert bootstrap.main(["--version", "9.9.9"]) == 0
    assert bootstrap.main(["--version", "9.9.9", "--prepare-only"]) == 0
    session.assert_not_called()


@pytest.mark.parametrize("holder", ["BC1", "BC4"])
def test_activate_with_authorized_lock_switches_current(monkeypatch, tmp_path, holder):
    _configure(monkeypatch, tmp_path, holder=holder)
    db = MagicMock()
    monkeypatch.setattr(bootstrap, "SessionLocal", lambda: db)
    invalidate = MagicMock(return_value={
        "rows_before": 1, "rows_deleted": 1, "rows_rebuilt": 1, "rows_after": 1,
    })
    monkeypatch.setattr(bootstrap, "invalidate_catalog_cache", invalidate)
    monkeypatch.setattr(
        bootstrap, "write_cache_invalidation_audit", lambda _report: tmp_path / "audit.json"
    )

    assert bootstrap.main(["--version", "9.9.9", "--activate"]) == 0
    assert len(db.execute.call_args_list) == 2
    assert "UPDATE catalog_release SET is_current=FALSE" in str(
        db.execute.call_args_list[0].args[0]
    )
    invalidate.assert_called_once_with(
        db,
        reason="catalog activation 9.9.9: bootstrap post-reset",
        source="bootstrap_catalog_release --activate",
    )
    db.commit.assert_called_once()
