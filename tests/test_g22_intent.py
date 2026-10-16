"""G22 (0.23.1) — Classification d'intention sur `/assistant`.

Vérifications :
- `classify_intent_heuristic` renvoie `conversation` sur « hello »,
  « bonjour », « qui es-tu », « comment tu marches », remerciement, etc.
- Renvoie `analyse` sur « combien d'opérateurs », « top 5 messages »,
  « compare les bandes », etc.
- Les questions mixtes (salutation + demande) → `analyse` l'emporte.
- Smoke live : POST /assistant avec question conversationnelle →
  shape minimale (pas de BlockSummary, pas d'Evidence `rrc_events`,
  scenario `conversation`).
- Smoke live : POST /assistant avec question analytique → shape 0.22.0
  conservée (BlockSummary présent, scenario `b2_enriched_context` sur
  projet ingéré).
"""

from __future__ import annotations

import os
import uuid

import pytest


pytestmark = pytest.mark.usefixtures("llm_state_sandbox")


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


# ---------- Partie unitaire : heuristique seule, sans LLM ----------


@pytest.mark.parametrize(
    "question,want",
    [
        ("hello", "conversation"),
        ("Bonjour !", "conversation"),
        ("salut", "conversation"),
        ("qui es-tu ?", "conversation"),
        ("comment tu marches ?", "conversation"),
        ("comment ça marche ?", "conversation"),
        ("merci", "conversation"),
        ("au revoir", "conversation"),
        ("présente-toi", "conversation"),
        ("que peux-tu faire ?", "conversation"),
        ("quels opérateurs sur ce projet ?", "analyse"),
        ("combien de messages RRC ?", "analyse"),
        ("Donne-moi le top 5 des messages RRC", "analyse"),
        ("Compare les bandes utilisées", "analyse"),
        ("Affiche la carte des RSRP", "analyse"),
        ("Quelle est la stratégie de mobilité ?", "analyse"),
        # Mixte : salutation + analyse → ANALYSE l'emporte (règle
        # tie-breaker : on ne vole pas d'info à l'utilisateur poli).
        ("Bonjour, combien d'opérateurs ?", "analyse"),
    ],
)
def test_heuristic(question: str, want: str) -> None:
    from app.services.intent import classify_intent_heuristic

    assert classify_intent_heuristic(question) == want


# ---------- Partie intégration : shape de réponse live ----------


def _project_id_with_rrc() -> str | None:
    from sqlalchemy import text

    from app.db import SessionLocal

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT project_id FROM param_occurrence "
                "GROUP BY project_id ORDER BY COUNT(*) DESC LIMIT 1"
            )
        ).first()
    return row[0] if row else None


def _ask(client, admin_tok, pid: str, question: str) -> dict:
    r = client.post(
        f"/projects/{pid}/assistant",
        headers=_hdr(admin_tok),
        json={
            "project_id": pid,
            "conversation_id": f"g22-{uuid.uuid4().hex[:8]}",
            "question": question,
            "filters": {"op": None, "tech": None, "svc": None, "band": None, "dep": None},
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_hello_is_conversation_shape(client_noauth, admin_tok):
    pid = _project_id_with_rrc()
    if pid is None:
        pytest.skip("Pas de projet ingéré en DB.")
    body = _ask(client_noauth, admin_tok, pid, "hello")
    # scenario = conversation
    assert body["scenario"] == "conversation", body["scenario"]
    # Aucun BlockSummary (pas de panneau Agrégats)
    types = [b.get("type") for b in body["blocks"]]
    assert "summary" not in types, types
    # Evidence vide (pas de panneau Sources)
    assert body["evidence"] == [], body["evidence"]
    # Aucun OBSERVED claim trompeur à n=0
    for b in body["blocks"]:
        for c in b.get("claims", []):
            assert c["kind"] != "OBSERVED", c


def test_analytical_question_keeps_shape(client_noauth, admin_tok):
    pid = _project_id_with_rrc()
    if pid is None:
        pytest.skip("Pas de projet ingéré en DB.")
    body = _ask(client_noauth, admin_tok, pid, "Donne-moi le top 5 des messages RRC")
    assert body["scenario"] == "b2_enriched_context", body["scenario"]
    types = [b.get("type") for b in body["blocks"]]
    assert "summary" in types, types
    srcs = {e["source_type"] for e in body["evidence"]}
    assert "rrc_events" in srcs, srcs
