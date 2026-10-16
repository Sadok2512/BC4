"""G24 (0.24.1) — Présentation d'accueil structurée (CONVERSATION).

Vérifications :
- "hello" → scénario `conversation`, 1 BlockText avec 1 claim INTERPRETED
  qui contient les 5 points de l'énoncé (qui / projet / capacités /
  comment / question ouverte), AUCUN BlockSummary, Evidence vide.
- La présentation ne contient AUCUN chiffre (aucune requête n'a été
  lancée en mode conversation — garanti par construction).
- Le nom du projet actif apparaît (le seul élément « dynamique » autorisé).
- Non-régression G22 : "Compare les bandes" → `b2_enriched_context`,
  BlockSummary présent, Evidence rrc_events.
"""

from __future__ import annotations

import json
import os
import re
import uuid

import pytest


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
            "conversation_id": f"g24-{uuid.uuid4().hex[:8]}",
            "question": question,
            "filters": {"op": None, "tech": None, "svc": None, "band": None, "dep": None},
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _project_name(client, admin_tok, pid: str) -> str:
    r = client.get(f"/projects/{pid}", headers=_hdr(admin_tok))
    assert r.status_code == 200, r.text
    return r.json()["name"]


def test_hello_welcome_structured(client_noauth, admin_tok):
    pid = _project_id_with_rrc()
    if pid is None:
        pytest.skip("Pas de projet ingéré en DB.")
    pname = _project_name(client_noauth, admin_tok, pid)

    body = _ask(client_noauth, admin_tok, pid, "hello")
    assert body["scenario"] == "conversation", body["scenario"]
    types = [b.get("type") for b in body["blocks"]]
    assert types == ["text"], types
    assert body["evidence"] == [], body["evidence"]

    # Un seul claim INTERPRETED, pas d'OBSERVED/UNAVAILABLE sur un accueil.
    claims = body["blocks"][0]["claims"]
    assert len(claims) == 1 and claims[0]["kind"] == "INTERPRETED"
    txt = claims[0]["text"]

    # 1) Qui : identifier BC4 + drive-test / NMF
    assert "assistant BC4" in txt
    assert "drive-test" in txt or "NMF" in txt

    # 2) Projet chargé + nom
    assert "Projet chargé" in txt
    assert pname in txt, f"nom projet absent: expected {pname!r} in text"

    # 3) Capacités (au moins 4 des 6 mots-clés listés)
    caps = [
        "opérateurs", "bandes", "messages RRC",
        "débits", "paramètres RRC", "cartes RSRP",
    ]
    hits = sum(1 for c in caps if c in txt)
    assert hits >= 4, f"Pas assez de capacités listées ({hits}/6) : {txt!r}"

    # 4) Comment je marche : « n=0 » / « inventer » / « sources »
    assert "n=0" in txt and "invent" in txt and "source" in txt.lower()

    # 5) Question ouverte finale
    assert "?" in txt

    # Aucun chiffre dans la présentation sauf « n=0 » autorisé.
    # On tolère quand même les chiffres dans le mot « n=0 » (déjà présent).
    # Grep défensif : aucun entier isolé ≥ 1 (hors "n=0") → présentation safe.
    sanitized = txt.replace("n=0", "")
    stray = re.findall(r"\b\d{1,}\b", sanitized)
    assert not stray, f"Chiffres isolés dans la présentation (hors n=0): {stray}"


def test_analysis_question_not_regressed(client_noauth, admin_tok):
    """Non-régression G22 : question factuelle → mode ANALYSE complet."""
    pid = _project_id_with_rrc()
    if pid is None:
        pytest.skip("Pas de projet ingéré en DB.")
    body = _ask(client_noauth, admin_tok, pid, "Compare les bandes utilisées")
    assert body["scenario"] == "b2_enriched_context", body["scenario"]
    types = [b.get("type") for b in body["blocks"]]
    assert "summary" in types, types
    srcs = {e["source_type"] for e in body["evidence"]}
    assert "rrc_events" in srcs, srcs
