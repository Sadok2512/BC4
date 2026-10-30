"""Fail-closed guard for operational commands that mutate a live database."""
from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_DEPLOY_LOCK_PATH = Path("/home/devmat/BC4/DEPLOY_LOCK")


class DeployLockError(RuntimeError):
    """The shared deployment lock is absent, malformed, or not held by BC3."""


def deploy_lock_path() -> Path:
    configured = os.environ.get("BC4_DEPLOY_LOCK_PATH")
    return Path(configured) if configured else DEFAULT_DEPLOY_LOCK_PATH


def require_bc3_deploy_lock(*, action: str, path: Path | None = None) -> Path:
    """Return the validated lock path or raise before any database write."""
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
    if holders[0] != "BC3":
        raise DeployLockError(
            f"DEPLOY_LOCK requis pour {action}: holder=BC3 attendu, holder={holders[0] or '<vide>'}"
        )
    return lock_path


def guard_bc3_deploy_lock(*, action: str) -> bool:
    """CLI adapter: emit an explicit verdict and return False on refusal."""
    try:
        path = require_bc3_deploy_lock(action=action)
    except DeployLockError as exc:
        print(f"VERDICT=FAIL reason=deploy_lock_required detail={exc}", file=sys.stderr)
        return False
    print(f"VERDICT=PASS deploy_lock holder=BC3 action={action} path={path}")
    return True
