"""G8 — authentification comptes locaux (B2).

Vérifications :
- login OK → 200 + token + user en vocabulaire FR (admin/ingenieur/lecteur) ;
- login KO (email inconnu OU mauvais mdp) → **même** 401, **même** message
  (aucune distinction qui laisserait fuir « email inconnu ») ;
- route protégée sans Bearer → 401 ;
- route protégée avec Bearer valide → 200 ;
- hash en DB jamais égal au mot de passe en clair, format argon2id ;
- /auth/me renvoie bien le profil courant.
"""

from __future__ import annotations

import os

import pytest

from sqlalchemy import text

from app.db import SessionLocal

ADMIN_EMAIL_ENV = "BC4_ADMIN_EMAIL"
ADMIN_PW_ENV = "BC4_ADMIN_PASSWORD"


def _admin_creds() -> tuple[str, str]:
    e, p = os.environ.get(ADMIN_EMAIL_ENV), os.environ.get(ADMIN_PW_ENV)
    if not e or not p:
        pytest.skip("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants pour G8")
    return e, p


def _login_admin(client_noauth) -> dict:
    email, pw = _admin_creds()
    r = client_noauth.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def test_login_success(client_noauth):
    body = _login_admin(client_noauth)
    assert body["token_type"] == "Bearer"
    assert isinstance(body["token"], str) and len(body["token"]) > 50
    assert body["user"]["role"] == "admin"
    assert body["user"]["active"] is True
    # Pas de fuite du mot de passe quelque part.
    import json
    assert "password" not in json.dumps(body).lower()


def test_login_bad_password_401(client_noauth):
    email, _ = _admin_creds()
    r = client_noauth.post("/auth/login", json={"email": email, "password": "WRONG-PW"})
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["code"] == "INVALID_CREDENTIALS"
    msg = body["detail"]["message"].lower()
    # Aucune indication qui distinguerait email vs mdp.
    for leak in ("mot de passe", "mdp", "password", "email", "introuvable", "exists"):
        assert leak not in msg


def test_login_unknown_email_401_same_shape(client_noauth):
    r = client_noauth.post(
        "/auth/login",
        json={"email": "nobody@nowhere.test", "password": "whatever"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_protected_without_bearer_401(client_noauth):
    r = client_noauth.get("/projects")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHENTICATED"


def test_protected_with_bearer_200(client_noauth):
    body = _login_admin(client_noauth)
    r = client_noauth.get("/projects", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 200


def test_me_returns_current_user(client_noauth):
    body = _login_admin(client_noauth)
    r = client_noauth.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 200
    assert r.json()["email"] == body["user"]["email"]
    assert r.json()["role"] == "admin"


def test_password_stored_as_argon2_hash():
    """Le mot de passe en clair ne doit JAMAIS être en base. argon2id
    préfixe tous ses hashs par `$argon2`."""
    email, pw = _admin_creds()
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT password_hash FROM app_user WHERE email = :e"),
            {"e": email.lower()},
        ).one()
    stored = row[0]
    assert stored and stored.startswith("$argon2"), stored[:16]
    assert pw not in stored


def test_logout_requires_bearer(client_noauth):
    r = client_noauth.post("/auth/logout")
    assert r.status_code == 401
    body = _login_admin(client_noauth)
    r = client_noauth.post("/auth/logout", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 204
