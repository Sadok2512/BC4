"""G10 (P1-2) — POST /settings/users + password policy + mapping 3-rôles.

Vérifications :
- 3 rôles distincts (admin, ingenieur, lecteur) → chaque login est OK,
  et un POST protégé renvoie {201/201 pour admin+ingenieur, 403 pour lecteur}.
- POST /settings/users avec mdp faible → 422 + détail (règle violée).
- POST /settings/users avec mdp conforme → 201 + user renvoyé (sans password).
- POST /settings/users par un ingenieur → 403 (admin only).
"""

from __future__ import annotations

import os
import uuid

import pytest


def _login(client_noauth, email: str, password: str) -> str:
    r = client_noauth.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    email = os.environ.get("BC4_ADMIN_EMAIL")
    pw = os.environ.get("BC4_ADMIN_PASSWORD")
    if not email or not pw:
        pytest.fail("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    return _login(client_noauth, email, pw)


@pytest.fixture(scope="module")
def ingenieur_tok(client_noauth) -> str:
    email = os.environ.get("BC4_DEMO_EMAIL")
    pw = os.environ.get("BC4_DEMO_PASSWORD")
    role = os.environ.get("BC4_DEMO_ROLE", "ingenieur")
    if not email or not pw:
        pytest.fail("BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquants (seed démo ingenieur attendu)")
    if role != "ingenieur":
        pytest.fail(f"BC4_DEMO_ROLE={role} — ce test attend ingenieur")
    return _login(client_noauth, email, pw)


@pytest.fixture(scope="module")
def lecteur_tok(client_noauth, admin_tok) -> str:
    """Crée (via l'API, admin) un compte lecteur jetable, retourne son token."""
    uid = uuid.uuid4().hex[:8]
    email = f"lecteur-{uid}"
    password = "LecteurPassw0rd!"
    r = client_noauth.post(
        "/settings/users",
        headers=_hdr(admin_tok),
        json={
            "login": email,
            "display_name": "Lecteur Test",
            "role": "viewer",  # Zod vocab → DB lecteur
            "password": password,
            "password_confirm": password,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "viewer"
    return _login(client_noauth, f"{email}@bc4.local", password)


def test_admin_can_post_protected(client_noauth, admin_tok):
    r = client_noauth.post("/projects", headers=_hdr(admin_tok), json={
        "name": f"g10-admin-{uuid.uuid4().hex[:6]}", "visibility": "private",
        "parse_decode_level": "light", "parse_binning_mode": "temporal",
        "parse_temporal_resolution": "native", "parse_spatial_bin_m": None,
    })
    assert r.status_code in {200, 201}, r.text


def test_ingenieur_can_post_protected(client_noauth, ingenieur_tok):
    r = client_noauth.post(
        "/projects",
        headers=_hdr(ingenieur_tok),
        json={"name": f"g10-ing-{uuid.uuid4().hex[:6]}", "visibility": "private",
              "parse_decode_level": "light", "parse_binning_mode": "temporal",
              "parse_temporal_resolution": "native", "parse_spatial_bin_m": None},
    )
    assert r.status_code in {200, 201}, r.text


def test_lecteur_cannot_post_protected(client_noauth, lecteur_tok):
    r = client_noauth.post(
        "/projects",
        headers=_hdr(lecteur_tok),
        json={"name": f"g10-lecteur-{uuid.uuid4().hex[:6]}", "visibility": "private",
              "parse_decode_level": "light", "parse_binning_mode": "temporal",
              "parse_temporal_resolution": "native", "parse_spatial_bin_m": None},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "FORBIDDEN"


def test_create_user_weak_password_422(client_noauth, admin_tok):
    r = client_noauth.post(
        "/settings/users",
        headers=_hdr(admin_tok),
        json={
            "login": f"weak-{uuid.uuid4().hex[:6]}",
            "display_name": "Weak Pass",
            "role": "viewer",
            "password": "abc",  # trop court, pas de maj, pas de chiffre
            "password_confirm": "abc",
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "WEAK_PASSWORD"
    # Les trois règles violées doivent apparaître dans le détail.
    msg = detail["message"].lower()
    assert "caractères" in msg or "characters" in msg
    assert "chiffre" in msg
    assert "majuscule" in msg
    assert "policy" in detail


def test_create_user_valid_password_201(client_noauth, admin_tok):
    uid = uuid.uuid4().hex[:8]
    login = f"ok-{uid}"
    password = "StrongPassw0rd!"
    r = client_noauth.post(
        "/settings/users",
        headers=_hdr(admin_tok),
        json={
            "login": login,
            "display_name": "Compte OK",
            "role": "editor",
            "password": password,
            "password_confirm": password,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "editor"
    assert body["active"] is True
    # Un mot de passe fourni par l'admin n'est jamais reflété.
    assert body["initial_password"] is None
    assert "password_hash" not in body

    # Le nouveau compte doit pouvoir se loger (preuve que app_user est bien créé).
    tok = _login(client_noauth, f"{login}@bc4.local", password)
    assert isinstance(tok, str) and len(tok) > 20


def test_create_user_generated_password_works_once(client_noauth, admin_tok):
    login = f"generated-{uuid.uuid4().hex[:8]}"
    r = client_noauth.post(
        "/settings/users", headers=_hdr(admin_tok),
        json={"login": login, "display_name": "Compte généré", "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    password = r.json()["initial_password"]
    assert isinstance(password, str) and password
    tok = _login(client_noauth, f"{login}@bc4.local", password)
    assert isinstance(tok, str) and len(tok) > 20


def test_ingenieur_cannot_create_user_403(client_noauth, ingenieur_tok):
    """Admin only sur POST /settings/users — ingenieur refusé."""
    r = client_noauth.post(
        "/settings/users",
        headers=_hdr(ingenieur_tok),
        json={
            "login": f"forbid-{uuid.uuid4().hex[:6]}",
            "display_name": "Forbid",
            "role": "viewer",
            "password": "AnotherStrong1!",
            "password_confirm": "AnotherStrong1!",
        },
    )
    assert r.status_code == 403
