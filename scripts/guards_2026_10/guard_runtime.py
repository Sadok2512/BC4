"""Fail-closed runtime bootstrap shared by manually executed guards."""
from __future__ import annotations

import os
import sys


def session_local_or_fail(guard: str):
    if not os.environ.get("BC4_DSN"):
        print(f"{guard} VERDICT=FAIL reason=missing_dsn")
        raise SystemExit(2)
    try:
        from app.db import SessionLocal
    except Exception as exc:
        print(
            f"{guard} VERDICT=FAIL reason=config_error "
            f"error={type(exc).__name__}"
        )
        raise SystemExit(2) from exc
    return SessionLocal
