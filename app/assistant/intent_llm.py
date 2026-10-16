"""Extraction d'intention par LLM structuré (0.33.0).

Remplace le détecteur Python heuristique (`intent.parse_intent`) qui
était fragile au phrasé : « montre moi la distribution RSRP » tombait
sur `operation=list, metric=operator_count`. Désormais, un appel LLM
court avec **structured output JSON** fait l'extraction, robuste au
phrasé/casse/mots de remplissage. Il ne produit AUCUN chiffre — juste
`{operation, metric_key, dimensions, comparison_dim, filters,
needs_clarification, reason}`.

Discipline préservée :
- `metric_key` DOIT être une clé exacte du catalogue, ou `null`.
- Si pas de métrique bindable → `needs_clarification=true` + raison.
  **JAMAIS un fallback silencieux vers `operator_count`.**
- Les salutations courtes sont court-circuitées par regex AVANT l'appel
  LLM (zéro coût sur « hello »).
- Si le LLM est désactivé / budget cap atteint / erreur réseau, le
  fallback est **l'heuristique Python** (intent.py) MAIS avec la même
  règle anti-fallback : pas de métrique bindable → NEEDS_CLARIFICATION,
  pas une liste par défaut.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.assistant.budget import check_budget
from app.assistant.intent import IntentPlan, parse_intent
from app.assistant.metrics import CATALOG
from app.services.llm_client import LlmInvocationError, call_llm
from app.services.llm_crypto import LlmCryptoError, get_effective_llm_config


logger = logging.getLogger(__name__)


# Court-circuit : les salutations/smalltalk vraiment courts ne vont
# pas au LLM (gain latence + coût).
_QUICK_CONVERSATION = re.compile(
    r"^\s*(hello|hi|hey|coucou|salut|bonjour|bonsoir|yo|wesh|"
    r"au\s+revoir|bye|a\s*\+|ciao|a\s+plus|merci|thanks|thx|"
    r"qui\s+(?:es|est)[-\s]?tu|t['e]s\s+qui|qui\s+êtes[-\s]?vous|"
    r"que\s+peux[-\s]?tu\s+faire|comment\s+tu\s+marches?|"
    r"présente[-\s]?toi|peux[-\s]?tu\s+te\s+présenter)"
    r"\s*[\?\.!]*\s*$",
    re.IGNORECASE,
)


def _catalog_card() -> str:
    """Carte publique du catalogue (clé, display, nature, unit, user_terms)
    envoyée au LLM comme référentiel. Pas de SQL, pas de path technique."""
    lines = []
    for key, m in CATALOG.items():
        terms = ", ".join(m.user_terms[:4])
        lines.append(
            f"- key={key} | display={m.display} | nature={m.nature} | "
            f"unit={m.unit} | class={m.comparability_class} | "
            f"user_terms=[{terms}]"
        )
    return "\n".join(lines)


_INTENT_SYSTEM_PROMPT = (
    "Tu es un EXTRACTEUR D'INTENTION pour l'assistant BC4 (benchmark radio).\n"
    "En entrée : une question utilisateur libre en français.\n"
    "En sortie : UN SEUL objet JSON strict, aucun chiffre, aucune narration.\n\n"
    "SCHEMA ATTENDU (clés exactes, pas de clé en plus) :\n"
    "{\n"
    "  \"operation\": \"conversation\" | \"list\" | \"distribution\" | \"compare\" | \"map\" | \"trend\" | \"describe\",\n"
    "  \"metric_key\": \"<clé_catalogue>\" | null,\n"
    "  \"dimensions\": [\"operator\"|\"band\"|\"system\"|\"message\"|\"param_path\"|\"value_raw\"|\"value_converted\"|\"dep\"],\n"
    "  \"comparison_dim\": \"operator\" | null,\n"
    "  \"filters\": [{\"dim\": \"operator\"|\"band\"|\"system\", \"op\": \"eq\"|\"in\", \"value\"?: str, \"values\"?: [str]}],\n"
    "  \"needs_clarification\": true | false,\n"
    "  \"reason\": \"string | null (si needs_clarification)\"\n"
    "}\n\n"
    "RÈGLES ABSOLUES :\n"
    "- `metric_key` DOIT être EXACTEMENT une clé du catalogue ci-dessous, ou null.\n"
    "  Mapper les synonymes français (ex. « puissance reçue » → rsrpServing, « débit » → throughputDL, « bandes » → band_count).\n"
    "- INTERDIT : inventer une clé qui n'est PAS dans le catalogue (ex. 'rsrp', 'rrc', 'ho_count'). Clé canonique uniquement.\n"
    "- Si la question demande une métrique MAIS que tu ne peux pas la binder au catalogue → `metric_key=null` ET `needs_clarification=true` + `reason` qui liste les candidats proches.\n"
    "- Pour `operation=compare` sans comparaison explicite → `comparison_dim=\"operator\"` et `dimensions` inclut \"operator\".\n"
    "- Pour `operation=distribution` sur une métrique à valeurs numériques → `dimensions=[\"value_raw\", \"value_converted\"]`.\n"
    "- Pour `operation=map` → `dimensions=[]`, metric_key doit être une métrique géo-locable (rsrpServing).\n"
    "- Pour `operation=list` → `dimensions` reflète ce que l'utilisateur veut lister (ex. opérateurs → [\"operator\"]).\n"
    "- Filtres : accepte opérateurs (Orange, SFR, Bouygues, Free) et bandes (B3, B20, n78…) détectés dans la question.\n"
    "- JAMAIS de chiffre numérique dans ta réponse (pas de 'Orange a 1000', pas de pourcentage).\n"
    "- Si le texte est une salutation ou un smalltalk → operation=conversation, metric_key=null, needs_clarification=false, dimensions=[].\n"
    "- Si tu doutes, préfère needs_clarification=true à inventer. **Pas de fallback silencieux vers operator_count.**\n"
    "- CASSE et MOTS DE REMPLISSAGE sans importance : « RSRP », « Rsrp », « rsrp » → même métrique. « montre moi », « donne moi », « affiche », « j'aimerais voir » → verbes de requête, pas de la sémantique.\n\n"
    "EXEMPLES (few-shot — reproduis strictement la forme JSON) :\n"
    "Q: « montre moi la distribution RSRP »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"rsrpServing\",\"dimensions\":[\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « distribution du rsrp »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"rsrpServing\",\"dimensions\":[\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « donne le rsrp en dBm »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"rsrpServing\",\"dimensions\":[\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « le rsrp par opérateur »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"rsrpServing\",\"dimensions\":[\"operator\",\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « affiche la puissance reçue »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"rsrpServing\",\"dimensions\":[\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « montre les débits »\n"
    "A: {\"operation\":\"distribution\",\"metric_key\":\"throughputDL\",\"dimensions\":[\"value_raw\",\"value_converted\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « quel temps fait-il »\n"
    "A: {\"operation\":\"list\",\"metric_key\":null,\"dimensions\":[],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":true,\"reason\":\"Aucune métrique radio liée au catalogue dans la question. Précise une grandeur mesurée (rsrp, rsrq, sinr, débit) ou un paramètre RRC (a3-Offset…).\"}\n"
    "Q: « hello »\n"
    "A: {\"operation\":\"conversation\",\"metric_key\":null,\"dimensions\":[],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n\n"
    "CATALOGUE AUTORISÉ :\n"
    "{catalog_card}\n\n"
    "Rends UNIQUEMENT le JSON (pas de ```, pas de commentaire)."
)


def _format_system_prompt() -> str:
    return _INTENT_SYSTEM_PROMPT.replace("{catalog_card}", _catalog_card())


def _ensure_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _parse_llm_json(txt: str) -> dict[str, Any] | None:
    """Tolérant aux fences ```json éventuels (si le modèle en met malgré
    l'instruction). Retourne None si parsing échoue."""
    s = (txt or "").strip()
    if s.startswith("```"):
        # Retire la première ligne fence et la dernière.
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _to_intent_plan(data: dict[str, Any], raw_q: str) -> IntentPlan | None:
    """Transforme la sortie LLM en `IntentPlan` validé contre le catalogue.
    Retourne None si le JSON est hors contrat (clé metric inventée, etc.)."""
    op = data.get("operation")
    if op not in ("conversation", "list", "distribution", "compare", "map", "trend", "describe"):
        return None
    metric_key = data.get("metric_key")
    if metric_key is not None:
        if metric_key not in CATALOG:
            # Clé inventée par le LLM → on refuse et on clarifie.
            logger.warning("intent_llm: metric_key %r inconnu, forcer clarification", metric_key)
            return IntentPlan(
                operation="list" if op not in ("conversation",) else "conversation",
                metric_key=None,
                raw_question=raw_q,
                ambiguous_terms=[str(metric_key)],
                ambiguous_candidates=[],
                needs_clarification=True,
                reason=f"Clé métrique {metric_key!r} inconnue du catalogue. "
                "Précise avec un libellé canonique (ex. rsrp, débits, bandes).",
            )

    dims = [str(d) for d in _ensure_list(data.get("dimensions")) if isinstance(d, str)]
    allowed_dims = {"operator", "band", "system", "message", "param_path", "value_raw", "value_converted", "dep"}
    dims = [d for d in dims if d in allowed_dims]

    comp = data.get("comparison_dim")
    if comp is not None and not isinstance(comp, str):
        comp = None
    if isinstance(comp, str) and comp not in allowed_dims:
        comp = None

    filters_raw = _ensure_list(data.get("filters"))
    filters: list[dict] = []
    for f in filters_raw:
        if not isinstance(f, dict):
            continue
        d = f.get("dim")
        o = f.get("op")
        if d not in allowed_dims or o not in ("eq", "in"):
            continue
        if o == "eq":
            v = f.get("value")
            if v is None:
                continue
            filters.append({"dim": d, "op": "eq", "value": str(v)})
        else:
            vs = f.get("values")
            if not isinstance(vs, list) or not vs:
                continue
            filters.append({"dim": d, "op": "in", "values": [str(x) for x in vs]})

    need_clarif = bool(data.get("needs_clarification"))
    reason = str(data.get("reason") or "")

    # Pour compare, assurer comparison_dim non vide.
    if op == "compare" and not comp:
        comp = "operator"
        if "operator" not in dims:
            dims = ["operator", *dims]

    plan = IntentPlan(
        operation=op,  # type: ignore[arg-type]
        metric_key=metric_key,
        dimensions=dims,
        comparison_dim=comp,
        filters=filters,
        raw_question=raw_q,
        needs_clarification=need_clarif,
        reason=reason,
    )

    # Discipline anti-fallback silencieux : si LLM dit `list`/`compare`
    # sans métrique ET pas de clarification → forcer clarification.
    if op in ("list", "compare", "distribution", "map", "trend") and metric_key is None and not need_clarif:
        plan.needs_clarification = True
        plan.reason = (
            "Aucune métrique canonique n'a été liée à la question. "
            "Précise la métrique (ex. rsrp, débits, bandes, opérateurs, a3-Offset)."
        )

    # Si distribution a bindé une métrique mais oublié les dims valeur :
    if op == "distribution" and metric_key and not any(d in dims for d in ("value_raw", "value_converted")):
        plan.dimensions = ["value_raw", "value_converted", *dims]

    return plan


def _apply_antifallback(plan: IntentPlan) -> IntentPlan:
    """Même règle anti-fallback pour un plan issu du fallback Python."""
    if (
        plan.operation in ("list", "compare", "distribution", "map", "trend")
        and plan.metric_key is None
        and not plan.needs_clarification
    ):
        plan.needs_clarification = True
        plan.reason = (
            "Aucune métrique canonique n'a été liée à la question "
            "(fallback heuristique). Précise la métrique souhaitée "
            "(ex. rsrp, débits, bandes, opérateurs, a3-Offset)."
        )
    return plan


def extract_intent(db: Session, question: str) -> IntentPlan:
    """Point d'entrée public : extrait l'intention de la question.

    Court-circuit salutation → heuristique rapide (zéro LLM).
    Sinon → appel LLM structured. Fallback heuristique si LLM down.
    """
    q = (question or "").strip()
    if not q:
        return parse_intent(q)

    # Court-circuit salutation / smalltalk sans coût LLM.
    if _QUICK_CONVERSATION.match(q):
        return parse_intent(q)

    # LLM disponible ?
    try:
        cfg = get_effective_llm_config(db)
    except LlmCryptoError as exc:
        logger.warning("intent_llm: config LLM illisible, fallback heuristique: %s", exc)
        return _apply_antifallback(parse_intent(q))

    enabled = cfg.get("enabled") and cfg.get("api_key") and cfg.get("provider") and cfg.get("base_url")
    if not enabled:
        return _apply_antifallback(parse_intent(q))

    ok_budget, _spent, _cap = check_budget(db, cfg.get("daily_cap_usd"))
    if not ok_budget:
        logger.warning("intent_llm: budget cap atteint, fallback heuristique")
        return _apply_antifallback(parse_intent(q))

    # Appel LLM court et borné.
    try:
        txt = call_llm(
            db,
            user_question=q,
            context_facts="",  # le prompt système contient tout
            system_prompt=_format_system_prompt(),
            max_tokens_override=350,
            timeout=15.0,
        )
    except LlmInvocationError as exc:
        logger.warning("intent_llm: appel LLM failed, fallback heuristique: %s", exc)
        return _apply_antifallback(parse_intent(q))

    if not txt:
        return _apply_antifallback(parse_intent(q))

    data = _parse_llm_json(txt)
    if data is None:
        logger.warning("intent_llm: JSON parse failed, fallback heuristique")
        return _apply_antifallback(parse_intent(q))

    plan = _to_intent_plan(data, q)
    if plan is None:
        return _apply_antifallback(parse_intent(q))

    return plan
