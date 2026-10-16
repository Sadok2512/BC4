"""G21 (0.22.0) — Contexte factuel enrichi pour l'Assistant.

Vérifications :
- Projet avec `param_occurrence > 0` (ex. TEST2 ingéré) : la réponse
  `/assistant` contient `scenario="b2_enriched_context"`, un deuxième
  claim OBSERVED « Dictionnaire RRC : N occurrences », une Evidence
  `rrc_events`, et un `SummaryItem` « Occurrences RRC décodées ».
- Projet avec `measurement_points > 0` et `param_occurrence == 0` : la
  réponse reste shape habituelle (`scenario="b2_sample_count"`), un
  seul claim OBSERVED, pas d'Evidence `rrc_events`.
- Projet totalement vide : scenario `b2_sample_count`, le LLM reçoit
  dans son contexte le garde-fou « ATTENTION: aucune mesure ni ... ».

On NE teste PAS le texte LLM (coûte des crédits + non déterministe).
On teste le shape de la réponse et la présence des OBSERVED/Evidence,
qui sont déterministes et reflètent la DB.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from app.db import SessionLocal


# 0.22.1 — G21 interroge /assistant mais ne mute PAS settings_llm.
# Néanmoins, en cas d'extension future, on garde le sandbox par
# précaution (coût nul si aucune mutation).
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


def _project_with_rrc(min_rrc: int = 1) -> str | None:
    """Retourne l'id d'un projet avec `param_occurrence > min_rrc`, ou None."""
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT project_id, COUNT(*) AS c
                FROM param_occurrence
                GROUP BY project_id
                ORDER BY c DESC
                LIMIT 1
                """
            )
        ).first()
    if row is None or row[1] < min_rrc:
        return None
    return row[0]


def _project_with_mp_no_rrc() -> str | None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT p.id
                FROM projects p
                WHERE EXISTS (SELECT 1 FROM measurement_points mp WHERE mp.project_id = p.id)
                AND NOT EXISTS (SELECT 1 FROM param_occurrence po WHERE po.project_id = p.id)
                LIMIT 1
                """
            )
        ).first()
    return row[0] if row else None


def _ask(client, admin_tok, project_id: str, question: str = "ping") -> dict:
    body = {
        "project_id": project_id,
        "conversation_id": f"g21-{uuid.uuid4().hex[:8]}",
        "question": question,
        "filters": {"op": None, "tech": None, "svc": None, "band": None, "dep": None},
    }
    r = client.post(
        f"/projects/{project_id}/assistant",
        headers=_hdr(admin_tok),
        json=body,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _observed_claims(body: dict) -> list[dict]:
    out = []
    for b in body.get("blocks", []):
        if b.get("type") == "text":
            for c in b.get("claims", []):
                if c.get("kind") == "OBSERVED":
                    out.append(c)
    return out


def _evidence_source_types(body: dict) -> set[str]:
    return {e.get("source_type") for e in body.get("evidence", [])}


def test_project_with_rrc_exposes_dict_counts(client_noauth, admin_tok):
    pid = _project_with_rrc()
    if pid is None:
        pytest.skip("Aucun projet avec param_occurrence en DB — ingère un NMF avant de lancer G21.")

    body = _ask(client_noauth, admin_tok, pid)
    assert body["scenario"] == "b2_enriched_context"

    observed = _observed_claims(body)
    # Au moins 2 OBSERVED (mesures + dict RRC).
    assert len(observed) >= 2, [c["text"] for c in observed]
    assert any("Dictionnaire RRC" in c["text"] for c in observed), observed
    assert any("occurrences" in c["text"].lower() for c in observed), observed

    srcs = _evidence_source_types(body)
    assert "measurement_points" in srcs
    assert "rrc_events" in srcs


def test_project_with_only_mp_keeps_old_shape(client_noauth, admin_tok):
    pid = _project_with_mp_no_rrc()
    if pid is None:
        pytest.skip("Aucun projet seedé (mp>0, rrc=0) — projets démo manquants.")

    body = _ask(client_noauth, admin_tok, pid)
    assert body["scenario"] == "b2_sample_count"

    observed = _observed_claims(body)
    # Un seul OBSERVED (mesures), pas de Dictionnaire RRC.
    assert len(observed) == 1, [c["text"] for c in observed]
    assert "Dictionnaire RRC" not in observed[0]["text"]

    srcs = _evidence_source_types(body)
    assert "measurement_points" in srcs
    assert "rrc_events" not in srcs


def test_context_builder_direct_shape():
    """Appel direct de `build_context_facts` : la chaîne doit contenir
    les préfixes `[MP]` et `[RRC]`, et marquer explicitement une alerte
    quand tout est à zéro."""
    from app.models import Project
    from app.schemas.assistant import AssistantFilters
    from app.services.assistant_context import build_context_facts

    with SessionLocal() as db:
        # Projet vide (ex. lille-indoor-2026 selon le seed). Prend n'importe
        # quel projet si tout a des données — on force à travailler sur un
        # scope filtré impossible pour simuler le vide.
        proj = db.query(Project).first()
        if proj is None:
            pytest.skip("Aucun projet en DB — rien à builder.")
        filters = AssistantFilters(op=["__does_not_exist__"])
        facts, meta = build_context_facts(db, proj, filters)
    assert "[MP]" in facts
    assert "[RRC]" in facts
    assert meta["mp_count"] == 0
    assert meta["rrc_count"] == 0
    assert "ATTENTION" in facts, facts
