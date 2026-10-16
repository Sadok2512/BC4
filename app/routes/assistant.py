"""Assistant IA — B0 minimal implementation.

B0 scope ships the contract and the shell so the front can call it; the
real scenario engine lands in B2 (déclaré comme écart ouvert dans
CHANGELOG). The response is built from DB observations (no hardcoded
values); scenario detection is intentionally shallow.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import ExecStepRow, Project
from app.assistant.compose import compose_response
from app.assistant.compose_v3 import compose_pipeline_response
from app.assistant.loop import run_agent
from app.assistant.pipeline import run_pipeline
from app.services.intent import classify_intent
from app.services.llm_crypto import get_effective_llm_config
from app.schemas.assistant import (
    AssistantRequest,
    AssistantResponse,
    BlockText,
    Claim,
    Conversation,
    ExecStep,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects",
    tags=["assistant"],
    dependencies=[Depends(get_current_user)],
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_steps(db: Session) -> list[ExecStep]:
    rows = db.query(ExecStepRow).order_by(ExecStepRow.position).all()
    return [ExecStep(id=r.id, label=r.label, duration_ms=r.duration_ms) for r in rows]


# 0.23.1 — Suggestions proposées à la fin d'une réponse CONVERSATION.
# Volontairement orientées « ouvre une analyse » — pour qu'un simple
# « hello » devienne une porte d'entrée vers du vrai contenu, pas un
# cul-de-sac. Statiques (pas de requête DB en mode conversation).
_CONVERSATION_FOLLOW_UPS = (
    "Quels opérateurs sont présents sur ce projet ?",
    "Donne-moi les 5 messages RRC les plus fréquents",
    "Compare les bandes utilisées",
    "Que peux-tu faire sur ce projet ?",
)


def _welcome_text(project: Project | None) -> str:
    """0.24.1 — Présentation structurée (5 points) renvoyée pour tout
    tour classé CONVERSATION. Template Python PUR : zéro appel LLM, zéro
    chiffre (le prompt « aucun chiffre sans requête » est garanti par
    construction, pas par un prompt système à qui on fait confiance).
    Le nom du projet actif est le SEUL élément dynamique autorisé —
    ce n'est pas un chiffre.

    Si `project` est None (ne devrait pas arriver sur la route actuelle
    qui 404 sans projet, mais safety net pour un futur call UI non-scopé),
    le texte invite à ouvrir un projet.
    """
    projet_line = (
        f"**Projet chargé** : « {project.name} »."
        if project is not None
        else "**Aucun projet chargé** — ouvre un projet dans « Projets » pour commencer."
    )
    return (
        "Je suis l'assistant BC4, ton assistant d'analyse des campagnes "
        "drive-test (logs NMF).\n\n"
        f"{projet_line}\n\n"
        "**Ce que je sais faire** :\n"
        "- opérateurs présents dans ton projet\n"
        "- bandes utilisées\n"
        "- messages RRC les plus fréquents\n"
        "- comparaison des débits par opérateur\n"
        "- paramètres RRC dominants (mobilité, timers, power control)\n"
        "- cartes RSRP / SINR\n\n"
        "**Comment je marche** : je réponds uniquement sur des agrégats "
        "de ton projet, je cite toujours mes sources, et je te dis "
        "clairement quand une donnée manque (n=0) au lieu d'inventer.\n\n"
        "Par quoi veux-tu commencer ?"
    )


def _build_conversation_response(
    db: Session, project: Project, body: AssistantRequest
) -> AssistantResponse:
    """Mode CONVERSATION (0.24.1) : présentation structurée **déterministe**
    en 5 points. AUCUN appel LLM (donc zéro invention possible, zéro
    coût provider sur un salut, zéro variance). AUCUNE requête DB.
    AUCUN BlockSummary, Evidence vide.

    Pré-0.24.1 : la route appelait `call_llm_conversation` qui pouvait
    renvoyer une ligne sèche genre « Bonjour ! Que souhaites-tu ? » —
    l'utilisateur n'avait aucune idée des capacités. Le lot 0.24.1
    livre une présentation fixe (template Python), couverture complète
    des 5 points de l'énoncé, zéro chiffre par construction.
    """
    claim = Claim(text=_welcome_text(project), kind="INTERPRETED")
    warnings: list[str] = []

    return AssistantResponse(
        conversation_id=body.conversation_id,
        message_id=str(uuid.uuid4()),
        status="completed",
        project_id=project.id,
        scenario="conversation",
        # Pas de « Données démo » sur une salutation — rien de synthétique.
        demo=False,
        effective_filters=body.filters,
        blocks=[BlockText(heading="", claims=[claim])],
        evidence=[],
        follow_ups=list(_CONVERSATION_FOLLOW_UPS),
        execution_steps=_load_steps(db),
        warnings=warnings,
    )


@router.post(
    "/{project_id}/assistant",
    response_model=AssistantResponse,
    response_model_exclude_none=True,
)
def post_assistant(
    project_id: str,
    body: AssistantRequest,
    db: Session = Depends(get_db),
) -> AssistantResponse:
    if body.project_id != project_id:
        raise HTTPException(400, {"code": "VALIDATION", "message": "project_id incohérent"})
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})

    # 0.23.1 — Classification d'intention. Un « hello » ne déclenche NI
    # requête DB NI panneau Agrégats/Sources. Un vrai « combien
    # d'opérateurs ? » suit le pipeline analytique complet. L'heuristique
    # résout > 90 % des cas sans coût LLM ; fallback LLM uniquement si
    # ambigu.
    intent = classify_intent(db, body.question)
    if intent == "conversation":
        return _build_conversation_response(db, project, body)

    # 0.28.0 — Pipeline V3 déterministe : le LLM n'écrit plus les
    # chiffres. Intent typé → faisabilité → exécution moteur → compose
    # déterministe (observed[] et verdict calculés par le code).
    # Narration LLM optionnelle et VÉRIFIÉE (0.28.0 : désactivée par
    # défaut tant que le vérificateur n'est pas étalonné en live).
    run_v3 = run_pipeline(db, project, body.question, conversation_id=body.conversation_id)
    composed = compose_pipeline_response(run_v3, project=project, filters=body.filters)
    message_id = str(uuid.uuid4())
    # 0.38.0 — skill_used (si l'intent LLM a sélectionné un skill actif).
    skill_used = composed.get("skill_used")
    skill_used_schema = None
    if skill_used:
        from app.schemas.assistant import SkillUsed
        skill_used_schema = SkillUsed(slug=skill_used["slug"], version=skill_used["version"])
    return AssistantResponse(
        conversation_id=body.conversation_id,
        message_id=message_id,
        status="completed",
        project_id=project_id,
        scenario=composed["scenario"],
        demo=False,  # 0.23.0 : "démo" ne reflète plus le flag staging — projets ingérés = False.
        effective_filters=body.filters,
        blocks=composed["blocks"],
        evidence=composed["evidence"],
        follow_ups=[
            "Comparer les débits par opérateur",
            "Lister les paramètres RRC dominants",
            "Afficher la carte des RSRP",
        ],
        execution_steps=_load_steps(db),
        warnings=composed["warnings"],
        skill_used=skill_used_schema,
    )


# Conversation history — MOCK-ONLY per Zod comments; B0 returns empty list
# (déclaré écart ouvert, voir CHANGELOG).
@router.get("/{project_id}/conversations", response_model=list[Conversation])
def list_conversations(project_id: str, db: Session = Depends(get_db)) -> list[Conversation]:
    if not db.get(Project, project_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})
    return []
