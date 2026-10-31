from pathlib import Path

import pytest

from app.scripts.deploy_guard import DeployLockError, require_deployer_lock


def test_refuses_missing_lock(tmp_path: Path):
    missing = tmp_path / "DEPLOY_LOCK"
    with pytest.raises(DeployLockError, match="illisible"):
        require_deployer_lock(action="test", path=missing)


def test_refuses_lock_held_by_another_agent(tmp_path: Path):
    lock = tmp_path / "DEPLOY_LOCK"
    lock.write_text("# BC4 DEPLOY LOCK\nholder: BC3\n", encoding="utf-8")
    with pytest.raises(DeployLockError, match="holder autorise parmi BC1,BC4, holder=BC3"):
        require_deployer_lock(action="test", path=lock)


@pytest.mark.parametrize("holder", ["BC1", "BC4"])
def test_accepts_lock_held_by_authorized_deployer(tmp_path: Path, holder: str):
    lock = tmp_path / "DEPLOY_LOCK"
    lock.write_text(f"# BC4 DEPLOY LOCK\nholder: {holder}\n", encoding="utf-8")
    assert require_deployer_lock(action="test", path=lock) == lock
