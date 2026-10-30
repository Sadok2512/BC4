from pathlib import Path

import pytest

from app.scripts.deploy_guard import DeployLockError, require_bc3_deploy_lock


def test_refuses_missing_lock(tmp_path: Path):
    missing = tmp_path / "DEPLOY_LOCK"
    with pytest.raises(DeployLockError, match="illisible"):
        require_bc3_deploy_lock(action="test", path=missing)


def test_refuses_lock_held_by_another_agent(tmp_path: Path):
    lock = tmp_path / "DEPLOY_LOCK"
    lock.write_text("# BC4 DEPLOY LOCK\nholder: BC4\n", encoding="utf-8")
    with pytest.raises(DeployLockError, match="holder=BC3 attendu, holder=BC4"):
        require_bc3_deploy_lock(action="test", path=lock)


def test_accepts_lock_held_by_bc3(tmp_path: Path):
    lock = tmp_path / "DEPLOY_LOCK"
    lock.write_text("# BC4 DEPLOY LOCK\nholder: BC3\n", encoding="utf-8")
    assert require_bc3_deploy_lock(action="test", path=lock) == lock
