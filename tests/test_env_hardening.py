from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(monkeypatch, env: str) -> Settings:
    monkeypatch.setenv("BC4_DSN", "postgresql+psycopg://test:test@db/test")
    monkeypatch.setenv("BC4_JWT_SECRET", "test-secret")
    monkeypatch.setenv("BC4_ENV", env)
    return Settings(_env_file=None)


def test_bc4_env_is_read(monkeypatch):
    assert _settings(monkeypatch, "production").env == "production"


def test_production_disables_fastapi_documentation(monkeypatch):
    import app.main as main

    assert main._documentation_urls("production") == {
        "docs_url": None, "redoc_url": None, "openapi_url": None,
    }


def test_unknown_environment_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        _settings(monkeypatch, "prod")


def test_about_uses_runtime_environment(monkeypatch):
    from app.routes import settings as route

    organization = MagicMock()
    organization.name = "BC4"
    db = MagicMock()
    db.query.return_value.one.return_value = organization
    monkeypatch.setattr(route.settings, "env", "production")

    assert route.get_about(db).environment == "production"
