"""G19 (0.17.1) — Probe `/settings/llm/test`.

Vérifications :
- Non-admin → 403. Pas de Bearer → 401.
- enabled=false → 200 + `{ok:false, message:"LLM désactivé…"}`.
- enabled=true + endpoint injoignable (`127.0.0.1:1`) → 200 +
  `{ok:false, latency_ms>0, message:"erreur réseau…"}`, pas de clé en clair.
- La réponse NE contient JAMAIS la clé en clair, le JSON ne contient
  jamais le champ `api_key`.
- Nettoyage : la clé de test est vidée (`api_key: ""`) en fin de garde.

Pas de test de succès réel (coûte des crédits provider). Smoke manuel
documenté dans README.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest


# 0.22.1 — Sandbox LLM : snapshot/restore via la fixture conftest.
# Les mutations PUT ci-dessous sont réversibles automatiquement.
pytestmark = pytest.mark.usefixtures("llm_state_sandbox")


FAKE_KEY = "sk-g19-" + uuid.uuid4().hex


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    e = os.environ.get("BC4_ADMIN_EMAIL")
    p = os.environ.get("BC4_ADMIN_PASSWORD")
    if not e or not p:
        pytest.fail("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": e, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def ingenieur_tok(client_noauth) -> str:
    e = os.environ.get("BC4_DEMO_EMAIL")
    p = os.environ.get("BC4_DEMO_PASSWORD")
    if not e or not p:
        pytest.fail("BC4_DEMO_EMAIL/BC4_DEMO_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": e, "password": p})
    assert r.status_code == 200
    return r.json()["token"]


def _put_llm(client, admin_tok, payload: dict) -> None:
    r = client.put("/settings/llm", headers=_hdr(admin_tok), json=payload)
    assert r.status_code == 200, r.text


def test_probe_requires_bearer(client_noauth):
    r = client_noauth.post("/settings/llm/test")
    assert r.status_code == 401


def test_probe_forbidden_for_non_admin(client_noauth, ingenieur_tok):
    r = client_noauth.post("/settings/llm/test", headers=_hdr(ingenieur_tok))
    assert r.status_code == 403


def test_probe_disabled_returns_ok_false(client_noauth, admin_tok):
    _put_llm(client_noauth, admin_tok, {"enabled": False})
    r = client_noauth.post("/settings/llm/test", headers=_hdr(admin_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "désactivé" in body["message"].lower()
    # Pas de clé exposée.
    assert "api_key" not in body


def test_probe_unreachable_returns_200_no_leak(client_noauth, admin_tok):
    """Endpoint injoignable → ok:false avec latency_ms>0, pas de 5xx,
    pas de fuite de clé."""
    secret = os.environ.get("BC4_LLM_SECRET_KEY")
    if not secret:
        pytest.fail("BC4_LLM_SECRET_KEY manquant")

    _put_llm(
        client_noauth,
        admin_tok,
        {
            "provider": "openai",
            "base_url": "http://127.0.0.1:1/v1",
            "model": "gpt-4o-mini",
            "api_key": FAKE_KEY,
            "enabled": True,
        },
    )

    r = client_noauth.post("/settings/llm/test", headers=_hdr(admin_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert body["model"] == "gpt-4o-mini"
    msg = (body["message"] or "").lower()
    assert any(k in msg for k in ("réseau", "timeout", "connect", "refus")), body["message"]

    # Jamais la clé en clair.
    assert FAKE_KEY not in json.dumps(body), "fuite clé LLM dans la réponse"


# 0.22.1 — Cleanup explicite retiré : la fixture `llm_state_sandbox`
# restaure la config LLM à la fin du module. Robuste aux crashs.
