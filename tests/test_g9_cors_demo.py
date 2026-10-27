"""G9 (P1-1) — CORS préflight depuis l'origine front + seed démo env.

Vérifications :
- OPTIONS depuis l'origine front renvoie 200 + access-control-allow-*
  cohérents (Authorization + Content-Type autorisés, POST autorisé).
- POST /projects authentifié depuis l'origine front → pas de blocage
  CORS (le header `Origin` passe sans provoquer de rejet avant
  dispatcher).
- OPTIONS depuis une origine non autorisée → pas d'access-control-allow-origin.
- Seed démo B2 : si BC4_DEMO_EMAIL/PASSWORD sont posés et que le compte
  n'existe pas, le seed le crée au démarrage de l'API.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.seed.run import _seed_demo_from_env


FRONT_ORIGIN = os.environ.get("BC4_FRONT_ORIGIN", "http://localhost:5174")


def test_preflight_from_front_origin_allowed(client_noauth):
    """OPTIONS depuis l'origine front doit renvoyer 200 + Allow-Origin."""
    r = client_noauth.request(
        "OPTIONS",
        "/projects",
        headers={
            "Origin": FRONT_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == FRONT_ORIGIN
    allow_methods = (r.headers.get("access-control-allow-methods") or "").upper()
    for m in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        assert m in allow_methods, f"méthode {m} absente du preflight"
    allow_headers = (r.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers


def test_preflight_from_unknown_origin_not_allowed(client_noauth):
    """OPTIONS depuis une origine inconnue : pas d'allow-origin échoué —
    aucun header permissif leaké."""
    r = client_noauth.request(
        "OPTIONS",
        "/projects",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Starlette renvoie 400 avec un `access-control-allow-origin` ABSENT.
    assert r.headers.get("access-control-allow-origin") is None


def test_authenticated_post_from_front_origin(client_noauth, admin_token):
    """POST authentifié depuis l'origine front = pas de blocage CORS."""
    r = client_noauth.post(
        "/projects",
        json={
            "name": f"g9-{uuid.uuid4().hex[:6]}", "visibility": "private",
            "parse_decode_level": "light", "parse_binning_mode": "temporal",
            "parse_temporal_resolution": "native", "parse_spatial_bin_m": None,
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Origin": FRONT_ORIGIN,
        },
    )
    assert r.status_code in {200, 201}, r.text
    # Et le header allow-origin est bien renvoyé sur la vraie requête.
    assert r.headers.get("access-control-allow-origin") == FRONT_ORIGIN


def test_demo_seed_from_env_idempotent():
    """Seed démo : si BC4_DEMO_EMAIL/PASSWORD sont posés, le compte est
    seedé une fois. Idempotent sur re-run."""
    email = os.environ.get("BC4_DEMO_EMAIL")
    pw = os.environ.get("BC4_DEMO_PASSWORD")
    if not email or not pw:
        pytest.fail("BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquants — skip seed démo")

    _seed_demo_from_env()
    with SessionLocal() as db:
        row1 = db.execute(
            text("SELECT role, active FROM app_user WHERE email = :e"),
            {"e": email.lower()},
        ).one_or_none()
    assert row1 is not None, "seed démo n'a pas créé le compte"
    assert row1.active is True

    # Re-run doit être idempotent : pas de doublon.
    _seed_demo_from_env()
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM app_user WHERE email = :e"),
            {"e": email.lower()},
        ).scalar()
    assert n == 1, "seed démo doit être idempotent"
