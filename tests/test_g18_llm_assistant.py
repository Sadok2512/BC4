"""G18 (0.17.0) — Assistant branché au LLM : robustesse + pas de fuite.

Vérifications :
- enabled=false → `/assistant` renvoie 200, un claim UNAVAILABLE indique
  « LLM désactivé », aucun appel HTTP n'est tenté.
- enabled=true + endpoint injoignable (`127.0.0.1:1`) → 200 avec claim
  UNAVAILABLE qui mentionne « indisponible » / « erreur réseau », JAMAIS 5xx.
- La réponse ne contient AUCUNE trace de la clé en clair.
- La DB stocke la clé chiffrée (préfixe Fernet) — non régressé depuis G17.
- `warnings` est populé quand une erreur LLM survient ; vide quand pas d'erreur.

On ne teste PAS un succès LLM réel ici — ça exigerait un provider live
avec facturation. Un smoke manuel suffit (déclaré ouvert).
"""

from __future__ import annotations

import os
import uuid

import pytest

from sqlalchemy import text

from app.db import SessionLocal


# 0.22.1 — Les mutations LLM de ce module sont encapsulées : la config
# `settings_llm` est snapshoté en entrée et restauré en sortie.
# JAMAIS de cleanup destructif qui laisse l'utilisateur sans clé.
pytestmark = pytest.mark.usefixtures("llm_state_sandbox")


FAKE_KEY = "sk-g18-" + uuid.uuid4().hex


def _hdr(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok(client_noauth) -> str:
    e = os.environ.get("BC4_ADMIN_EMAIL")
    p = os.environ.get("BC4_ADMIN_PASSWORD")
    if not e or not p:
        pytest.skip("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": e, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def project_id(client_noauth, admin_tok) -> str:
    """Récupère un projet existant (seedé). Si aucun, skip."""
    r = client_noauth.get("/projects", headers=_hdr(admin_tok))
    assert r.status_code == 200
    projects = r.json()
    if not projects:
        pytest.skip("Aucun projet seedé — G18 skip.")
    return projects[0]["id"]


def _post_assistant(client, admin_tok, pid: str) -> dict:
    body = {
        "project_id": pid,
        "conversation_id": f"g18-{uuid.uuid4().hex[:8]}",
        "question": "Résume le périmètre.",
        "filters": {"op": None, "tech": None, "svc": None, "band": None, "dep": None},
    }
    r = client.post(
        f"/projects/{pid}/assistant",
        headers=_hdr(admin_tok),
        json=body,
    )
    return r


def _put_llm(client, admin_tok, payload: dict) -> None:
    r = client.put("/settings/llm", headers=_hdr(admin_tok), json=payload)
    assert r.status_code == 200, r.text


def test_assistant_llm_disabled_returns_claim_not_500(
    client_noauth, admin_tok, project_id
):
    """enabled=false → 200 + claim UNAVAILABLE 'désactivé'. Jamais 500."""
    # Désactive via PUT (idempotent).
    _put_llm(client_noauth, admin_tok, {"enabled": False})

    r = _post_assistant(client_noauth, admin_tok, project_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"

    # Au moins un claim UNAVAILABLE qui mentionne la désactivation.
    all_text = " ".join(
        c["text"] for b in body["blocks"] if b.get("type") == "text" for c in b["claims"]
    )
    assert "désactivé" in all_text.lower() or "non configuré" in all_text.lower(), all_text

    # Aucun warning LLM (puisqu'on n'a pas tenté d'appel).
    assert body["warnings"] == [] or not any(
        "LLM invoked" in w for w in body["warnings"]
    )


def test_assistant_llm_unreachable_returns_200_not_500(
    client_noauth, admin_tok, project_id
):
    """enabled=true + endpoint injoignable → 200 + claim UNAVAILABLE.
    PAS de 500 : la UI préfère un claim « indisponible » à un crash."""
    secret = os.environ.get("BC4_LLM_SECRET_KEY")
    if not secret:
        pytest.skip("BC4_LLM_SECRET_KEY manquant — PUT clé impossible")

    _put_llm(
        client_noauth,
        admin_tok,
        {
            "provider": "openai",
            # Port 1 → connexion refusée immédiatement (pas de timeout long).
            "base_url": "http://127.0.0.1:1/v1",
            "model": "gpt-4o-mini",
            "api_key": FAKE_KEY,
            "enabled": True,
        },
    )

    r = _post_assistant(client_noauth, admin_tok, project_id)
    # Garde la plus importante : pas de 5xx côté API, même si le LLM
    # côté réseau est injoignable.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"

    import json
    dump = json.dumps(body)
    # Fuite de clé : jamais.
    assert FAKE_KEY not in dump, "fuite clé LLM dans la réponse"

    # Un claim doit expliciter l'indisponibilité.
    all_text = " ".join(
        c["text"] for b in body["blocks"] if b.get("type") == "text" for c in b["claims"]
    )
    assert (
        "indisponible" in all_text.lower()
        or "réseau" in all_text.lower()
        or "timeout" in all_text.lower()
    ), all_text

    # `warnings` doit mentionner l'échec LLM (traçabilité UI).
    assert any("LLM invoked" in w or "fallback" in w.lower() for w in body["warnings"]), body["warnings"]


def test_db_still_stores_cipher_not_plaintext():
    """Non-régression G17 : la clé en DB reste chiffrée (Fernet)."""
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT api_key_cipher FROM settings_llm WHERE id = 1")
        ).one()
    cipher = row[0]
    if cipher is None:
        pytest.skip("Pas de clé posée — rien à vérifier")
    assert cipher != FAKE_KEY, "LEAK: clé stockée en clair"
    assert cipher.startswith("gAAAAA"), f"pas un token Fernet: {cipher[:10]}"


# 0.22.1 — Le cleanup explicite (`api_key:""` + `enabled:false`) est
# retiré : le sandbox module-scoped (`llm_state_sandbox`) restaure la
# config LLM au moment où ce module se termine, cleanly ou en crash.
# Un test qui mute un état partagé doit toujours passer par ce chemin.
