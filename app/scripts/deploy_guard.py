"""Fail-closed guard for operational commands that mutate a live database."""
from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_DEPLOY_LOCK_PATH = Path("/home/devmat/BC4/DEPLOY_LOCK")


class DeployLockError(RuntimeError):
    """The shared deployment lock is absent, malformed, or held by another actor."""


AUTHORIZED_DEPLOY_HOLDERS = frozenset({"BC1", "BC4"})


def deploy_lock_path() -> Path:
    configured = os.environ.get("BC4_DEPLOY_LOCK_PATH")
    return Path(configured) if configured else DEFAULT_DEPLOY_LOCK_PATH


def _validated_deploy_lock(*, action: str, path: Path | None = None) -> tuple[Path, str]:
    lock_path = path or deploy_lock_path()
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeployLockError(
            f"DEPLOY_LOCK illisible path={lock_path}: {exc.strerror or exc}"
        ) from exc

    holders = []
    for line in content.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "holder":
            holders.append(value.strip())
    if len(holders) != 1:
        raise DeployLockError(
            f"DEPLOY_LOCK invalide path={lock_path}: un unique champ holder est requis"
        )
    if holders[0] not in AUTHORIZED_DEPLOY_HOLDERS:
        raise DeployLockError(
            f"DEPLOY_LOCK requis pour {action}: holder autorise parmi "
            f"{','.join(sorted(AUTHORIZED_DEPLOY_HOLDERS))}, "
            f"holder={holders[0] or '<vide>'}"
        )
    return lock_path, holders[0]


def require_deployer_lock(*, action: str, path: Path | None = None) -> Path:
    """Return the validated lock path or raise before any database write."""
    lock_path, _holder = _validated_deploy_lock(action=action, path=path)
    return lock_path


def guard_deployer_lock(*, action: str) -> bool:
    """CLI adapter: emit an explicit verdict and return False on refusal."""
    try:
        path, holder = _validated_deploy_lock(action=action)
    except DeployLockError as exc:
        print(f"VERDICT=FAIL reason=deploy_lock_required detail={exc}", file=sys.stderr)
        return False
    print(f"VERDICT=PASS deploy_lock holder={holder} action={action} path={path}")
    return True


# Compatibility aliases used by operational scripts released before 0.118.2.
# Their names are intentionally retained while their authorization policy is
# now BC1-or-BC4, enforced by the single implementation above.
require_bc3_deploy_lock = require_deployer_lock
guard_bc3_deploy_lock = guard_deployer_lock
