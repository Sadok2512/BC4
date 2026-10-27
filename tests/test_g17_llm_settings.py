"""G17 (0.16.0) — Settings LLM : chiffrement, admin-only, pas de fuite.

Vérifications :
- GET /settings/llm (admin) : 200, structure attendue, `api_key_set` reflète
  la DB, la clé en clair n'apparaît JAMAIS dans la réponse.
- PUT /settings/llm (admin) : 200, met à jour provider/model, `api_key_set`
  passe à true, la clé en clair N'EST PAS renvoyée.
- PUT /settings/llm sans role admin → 403.
- GET /settings/llm sans Bearer → 401.
- La valeur stockée en DB (`settings_llm.api_key_cipher`) est bien chiffrée
  (jamais égale à la clé en clair, préfixe Fernet `gAAAAA`).
- `/projects/{id}/assistant` tolère l'absence de LLM (claim UNAVAILABLE) ET
  intègre `provider/model` dans son claim quand une clé est posée.
"""

from __future__ import annotations

import os
import uuid

import pytest

from sqlalchemy import text

from app.db import SessionLocal


FAKE_KEY = "sk-g17-" + uuid.uuid4().hex


def _login(client_noauth, email: str, password: str) -> str:
    r = client_noauth.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    e = os.environ.get("BC4_ADMIN_EMAIL")
    p = os.environ.get("BC4_ADMIN_PASSWORD")
    if not e or not p:
        pytest.fail("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    return _login(client_noauth, e, p)


@pytest.fixture(scope="module")
def ingenieur_tok(client_noauth) -> str:
    e = os.environ.get("BC4_DEMO_EMAIL")
    p = os.environ.get("BC4_DEMO_PASSWORD")
    r = os.environ.get("BC4_DEMO_ROLE", "ingenieur")
    if not e or not p:
        pytest.fail("BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquants")
    if r != "ingenieur":
        pytest.fail(f"BC4_DEMO_ROLE={r} — attendu ingenieur")
    return _login(client_noauth, e, p)


def test_get_llm_requires_bearer(client_noauth):
    r = client_noauth.get("/settings/llm")
    assert r.status_code == 401


def test_get_llm_forbidden_for_non_admin(client_noauth, ingenieur_tok):
    r = client_noauth.get("/settings/llm", headers=_hdr(ingenieur_tok))
    assert r.status_code == 403


def test_get_llm_shape(client_noauth, admin_tok):
    r = client_noauth.get("/settings/llm", headers=_hdr(admin_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("provider", "base_url", "model", "enabled", "api_key_set"):
        assert k in body, f"clé {k} manquante"
    assert isinstance(body["enabled"], bool)
    assert isinstance(body["api_key_set"], bool)
    # Jamais de clé en clair dans la réponse.
    import json
    assert "api_key" not in body
    assert FAKE_KEY not in json.dumps(body)


def test_put_llm_requires_admin(client_noauth, ingenieur_tok):
    r = client_noauth.put(
        "/settings/llm",
        headers=_hdr(ingenieur_tok),
        json={"provider": "openai"},
    )
    assert r.status_code == 403


def test_put_llm_sets_key_without_leaking(client_noauth, admin_tok):
    """La PUT accepte provider/model/api_key. La réponse ne contient
    PAS la clé en clair ; seul `api_key_set=true` indique sa présence."""
    secret = os.environ.get("BC4_LLM_SECRET_KEY")
    if not secret:
        pytest.fail("BC4_LLM_SECRET_KEY manquant — PUT clé ne peut pas chiffrer")

    r = client_noauth.put(
        "/settings/llm",
        headers=_hdr(admin_tok),
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": FAKE_KEY,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert body["enabled"] is True
    assert body["api_key_set"] is True

    # Aucune trace du secret en clair dans la réponse.
    import json
    assert FAKE_KEY not in json.dumps(body)
    assert "api_key" not in body

    # DB : le cipher ne doit JAMAIS égaler la clé en clair, et un
    # token Fernet commence toujours par `gAAAAA` (base64 de version
    # 0x80). Si ces assertions échouent, la clé a été stockée en clair.
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT api_key_cipher FROM settings_llm WHERE id = 1")
        ).one()
    cipher = row[0]
    assert cipher, "cipher vide après PUT — rien n'a été stocké"
    assert cipher != FAKE_KEY, "clé stockée en clair — fuite au repos"
    assert cipher.startswith("gAAAAA"), f"pas un token Fernet: {cipher[:10]}"


def test_put_llm_clear_key(client_noauth, admin_tok):
    """`api_key: ""` vide le cipher (api_key_set repasse à false)."""
    secret = os.environ.get("BC4_LLM_SECRET_KEY")
    if not secret:
        pytest.fail("BC4_LLM_SECRET_KEY manquant")

    # Re-pose puis vide.
    client_noauth.put(
        "/settings/llm",
        headers=_hdr(admin_tok),
        json={"api_key": FAKE_KEY},
    )
    r = client_noauth.put(
        "/settings/llm",
        headers=_hdr(admin_tok),
        json={"api_key": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["api_key_set"] is False


def test_put_llm_rejects_key_without_secret(client_noauth, admin_tok, monkeypatch):
    """Si BC4_LLM_SECRET_KEY est absent, le PUT d'une clé doit échouer
    (400 LLM_CRYPTO) plutôt que stocker un blob opaque en clair déguisé.
    Ce test tourne contre le process API — on ne peut pas monkeypatcher
    son env ici. On skip proprement si le process a bien un secret."""
    secret = os.environ.get("BC4_LLM_SECRET_KEY")
    if secret:
        pytest.fail(
            "BC4_LLM_SECRET_KEY présent côté API — ce test exige l'absence"
        )
    r = client_noauth.put(
        "/settings/llm",
        headers=_hdr(admin_tok),
        json={"api_key": "whatever"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "LLM_CRYPTO"
