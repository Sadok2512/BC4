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

from app.assistant.budget import check_budget, log_usage
from app.assistant.intent import IntentPlan, parse_intent
from app.assistant.metrics import CATALOG
from app.services.llm_client import LlmInvocationError, call_llm_with_usage
from app.services.llm_crypto import LlmCryptoError, get_effective_llm_config
from app.services.skills import ALLOWED_TOOLS, extract_defaults, load_active_skills


logger = logging.getLogger(__name__)


# 0.37.0 — Marqueur « l'utilisateur veut un count ». Permet de reconnaître
# que « combien d'occurrences a3-Offset par opérateur » doit sortir un
# count (74/40/18) alors que « compare a3-Offset » doit sortir la
# distribution de ses VALEURS. Par le CONTENU — jamais sur l'étiquette.
_WANTS_COUNT = re.compile(
    r"\b(combien|nombre\s+d['e]|nb\s+d['e]|count|compte|occurrence)",
    re.IGNORECASE,
)


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
    "  \"reason\": \"string | null (si needs_clarification)\",\n"
    "  \"skill_slug\": \"<slug_skill_actif>\" | null\n"
    "}\n\n"
    "SKILLS ACTIFS (0.38.0) : si la liste `SKILLS_ACTIFS` ci-dessous n'est pas vide, tu PEUX\n"
    "sélectionner UN seul skill dont les `triggers` collent sémantiquement à la question.\n"
    "`skill_slug` = le slug choisi, ou `null` si aucun ne colle. Un skill GUIDE l'exécution\n"
    "(outils autorisés, procédure déclarative) ; il NE REMPLACE PAS les règles ci-dessus et\n"
    "ne change JAMAIS `metric_key`/`operation` extraits de la question. Si la question est\n"
    "ambiguë, préfère `skill_slug=null` à inventer.\n\n"
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
    "- CASSE et MOTS DE REMPLISSAGE sans importance : « RSRP », « Rsrp », « rsrp » → même métrique. « montre moi », « donne moi », « affiche », « j'aimerais voir » → verbes de requête, pas de la sémantique.\n"
    "- NORMALISATION DES NOMS DE PARAMÈTRES RRC (insensible casse / tirets / espaces) :\n"
    "  « a3offset », « A3offset », « a3 offset », « A3 Offset », « a3-offset » → clé catalogue `a3Offset`.\n"
    "  « a5threshold1 », « a5 threshold1 » → `a5Threshold1`.\n"
    "  « thresholdRSRP », « threshold rsrp » → à mapper si la clé existe au catalogue ; sinon metric_key=null + needs_clarification.\n"
    "  « TTT », « timeToTrigger », « time to trigger » → à mapper si clé catalogue existe ; sinon needs_clarification.\n"
    "- RÈGLE DURE SUR LES PARAMÈTRES RRC (`nature=config` OU `nature=measurement`) :\n"
    "  « compare le paramètre X », « X par opérateur », « compare X entre opérateurs » → operation=compare,\n"
    "  metric_key=<clé catalogue de X>, dimensions=[\"operator\",\"value_raw\",\"value_converted\"],\n"
    "  comparison_dim=\"operator\". JAMAIS un count d'occurrences par opérateur en résultat principal\n"
    "  pour un paramètre : un paramètre se compare par SES VALEURS.\n"
    "- EXCEPTION — l'utilisateur demande EXPLICITEMENT un count : « combien d'occurrences X », « nombre de X »,\n"
    "  « compte X par opérateur » → operation=list, dimensions=[\"operator\"], count d'occurrences.\n\n"
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
    "Q: « compare a3-Offset »\n"
    "A: {\"operation\":\"compare\",\"metric_key\":\"a3Offset\",\"dimensions\":[\"operator\",\"value_raw\",\"value_converted\"],\"comparison_dim\":\"operator\",\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « compare le parametre A3offset »\n"
    "A: {\"operation\":\"compare\",\"metric_key\":\"a3Offset\",\"dimensions\":[\"operator\",\"value_raw\",\"value_converted\"],\"comparison_dim\":\"operator\",\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « A3offset par opérateur »\n"
    "A: {\"operation\":\"compare\",\"metric_key\":\"a3Offset\",\"dimensions\":[\"operator\",\"value_raw\",\"value_converted\"],\"comparison_dim\":\"operator\",\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « compare a3 offset entre opérateurs »\n"
    "A: {\"operation\":\"compare\",\"metric_key\":\"a3Offset\",\"dimensions\":[\"operator\",\"value_raw\",\"value_converted\"],\"comparison_dim\":\"operator\",\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « combien d'occurrences a3-Offset par opérateur »\n"
    "A: {\"operation\":\"list\",\"metric_key\":\"a3Offset\",\"dimensions\":[\"operator\"],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n"
    "Q: « quel temps fait-il »\n"
    "A: {\"operation\":\"list\",\"metric_key\":null,\"dimensions\":[],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":true,\"reason\":\"Aucune métrique radio liée au catalogue dans la question. Précise une grandeur mesurée (rsrp, rsrq, sinr, débit) ou un paramètre RRC (a3-Offset…).\"}\n"
    "Q: « hello »\n"
    "A: {\"operation\":\"conversation\",\"metric_key\":null,\"dimensions\":[],\"comparison_dim\":null,\"filters\":[],\"needs_clarification\":false,\"reason\":null}\n\n"
    "CATALOGUE AUTORISÉ :\n"
    "{catalog_card}\n\n"
    "SKILLS_ACTIFS :\n"
    "{skills_card}\n\n"
    "Rends UNIQUEMENT le JSON (pas de ```, pas de commentaire)."
)


def _skills_card(skills: list) -> str:
    """Carte publique des skills actifs (slug, name, description,
    triggers tronqués). Pas de body ni Procédure — c'est au pipeline
    d'injecter la Procédure si le skill est retenu."""
    if not skills:
        return "(aucun skill actif)"
    lines = []
    for s in skills:
        tr = ", ".join((s.triggers or [])[:6])
        lines.append(
            f"- slug={s.slug} | version={s.version} | name={s.name} | "
            f"description={s.description} | triggers=[{tr}]"
        )
    return "\n".join(lines)


def _format_system_prompt(skills: list | None = None) -> str:
    return (
        _INTENT_SYSTEM_PROMPT
        .replace("{catalog_card}", _catalog_card())
        .replace("{skills_card}", _skills_card(skills or []))
    )


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


def _to_intent_plan(
    data: dict[str, Any],
    raw_q: str,
    active_skills: list | None = None,
) -> IntentPlan | None:
    """Transforme la sortie LLM en `IntentPlan` validé contre le catalogue.
    Retourne None si le JSON est hors contrat (clé metric inventée, etc.)."""
    active_skills = active_skills or []
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

    # 0.37.0 — Un paramètre se compare par ses VALEURS, jamais par un
    # count d'occurrences. Si le LLM a rendu `compare` sur un paramètre
    # (`nature=config` OU `nature=measurement`) sans injecter de dim
    # valeur, on la force. Garde l'`operator` déjà présent (le pivot
    # compose exige operator × value).
    #
    # Exception explicite : si la question demande un count (regex
    # local « combien|nombre d'occurrences|compte »), on bascule
    # `compare → list` sans dim valeur — c'est le seul chemin où un
    # count par opérateur est le résultat légitime.
    if op == "compare" and metric_key:
        m = CATALOG.get(metric_key)
        nature = getattr(m, "nature", None)
        wants_count = bool(_WANTS_COUNT.search(raw_q or ""))
        if nature in ("config", "measurement") and not wants_count:
            if not any(d in plan.dimensions for d in ("value_raw", "value_converted")):
                # Insère les dims valeur APRÈS operator pour conserver
                # l'intuition « par opérateur, voici les valeurs ».
                new_dims = list(plan.dimensions)
                if "operator" not in new_dims:
                    new_dims = ["operator", *new_dims]
                for extra in ("value_raw", "value_converted"):
                    if extra not in new_dims:
                        new_dims.append(extra)
                plan.dimensions = new_dims
                logger.info(
                    "intent_llm: compare on %s nature=%s → force value_* dims=%s",
                    metric_key, nature, plan.dimensions,
                )
        elif wants_count:
            # Count explicitement demandé : on redescend sur `list` et
            # on ne garde que `operator` comme dim.
            plan.operation = "list"
            plan.comparison_dim = None
            plan.dimensions = ["operator"]
            logger.info(
                "intent_llm: count-explicit on %s → op=list dims=[operator]",
                metric_key,
            )

    # 0.38.0 — Skills : si le LLM a sélectionné un skill, on vérifie
    # qu'il appartient à la liste ACTIVE (pas de slug inventé) et on
    # narrow sa liste d'outils à `tools_allowed ∩ ALLOWED_TOOLS`
    # (jamais un outil hors moteur).
    chosen = data.get("skill_slug")
    match: Any = None
    if isinstance(chosen, str) and chosen:
        match = next((s for s in active_skills if s.slug == chosen), None)
        if match is None:
            logger.warning(
                "intent_llm: skill_slug %r inconnu dans les skills actifs — ignoré",
                chosen,
            )

    # 0.38.0 — Fallback déterministe : si le LLM n'a pas sélectionné un
    # skill (ou a sélectionné un slug inconnu), on scanne les triggers
    # ACTIFS par CONTENU dans la question. Insensible à la casse. Le
    # premier skill dont un trigger apparaît en substring dans la
    # question est retenu. Cette garde évite de dépendre de la
    # fiabilité du modèle sur le champ optionnel `skill_slug`.
    if match is None and active_skills:
        qlow = (raw_q or "").lower()
        for s in active_skills:
            for t in s.triggers or []:
                tl = str(t).strip().lower()
                if tl and tl in qlow:
                    match = s
                    logger.info(
                        "intent_llm: skill picked by deterministic trigger "
                        "match: slug=%s trigger=%r",
                        s.slug, tl,
                    )
                    break
            if match is not None:
                break

    if match is not None:
        plan.skill_slug = match.slug
        plan.skill_version = match.version
        # Intersection stricte avec la liste blanche du moteur.
        plan.skill_tools_allowed = sorted(
            set(match.tools_allowed or []) & ALLOWED_TOOLS
        )

        # 0.38.0 — Si le skill déclare un `default_metric` /
        # `default_operation` dans son frontmatter, on les applique
        # UNIQUEMENT quand l'extracteur LLM n'a pas bindé la métrique
        # (metric_key=null) OU est resté sur `describe` par défaut.
        # Le skill GUIDE : il ne peut PAS écraser une métrique déjà
        # bindée par la question (invariant « par le contenu »).
        default_metric, default_operation = extract_defaults(match.body_md)
        if default_metric and default_metric in CATALOG and plan.metric_key is None:
            plan.metric_key = default_metric
            # Si on vient de binder une métrique, on lève le flag
            # needs_clarification posé par le safety-net plus haut.
            if plan.needs_clarification and plan.reason.startswith("Aucune métrique canonique"):
                plan.needs_clarification = False
                plan.reason = ""
            logger.info(
                "intent_llm: skill %s default_metric=%s appliqué (LLM avait metric=null)",
                match.slug, default_metric,
            )
        if default_operation and plan.operation in ("describe",):
            plan.operation = default_operation  # type: ignore[assignment]
            logger.info(
                "intent_llm: skill %s default_operation=%s appliqué (LLM avait op=describe)",
                match.slug, default_operation,
            )

        # Si la combinaison résultante est compare sur une métrique de
        # paramètre (nature config/measurement) sans dims valeur, on
        # applique la même garde que 0.37.0 — pivot operator × value.
        if plan.operation == "compare" and plan.metric_key:
            m2 = CATALOG.get(plan.metric_key)
            if m2 is not None and m2.nature in ("config", "measurement"):
                if not any(d in plan.dimensions for d in ("value_raw", "value_converted")):
                    new_dims = list(plan.dimensions)
                    if "operator" not in new_dims:
                        new_dims = ["operator", *new_dims]
                    for extra in ("value_raw", "value_converted"):
                        if extra not in new_dims:
                            new_dims.append(extra)
                    plan.dimensions = new_dims
                    plan.comparison_dim = plan.comparison_dim or "operator"
                    logger.info(
                        "intent_llm: skill post-fix compare dims=%s",
                        plan.dimensions,
                    )

        logger.info(
            "intent_llm: skill_used slug=%s version=%s tools_allowed=%s",
            plan.skill_slug, plan.skill_version, plan.skill_tools_allowed,
        )

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


def extract_intent(
    db: Session,
    question: str,
    *,
    conversation_id: str | None = None,
) -> IntentPlan:
    """Point d'entrée public : extrait l'intention de la question.

    Court-circuit salutation → heuristique rapide (zéro LLM).
    Sinon → appel LLM structured. Fallback heuristique si LLM down.

    0.34.1 — Trace `INFO` systématique du chemin pris (`llm`, `fallback-*`,
    `conversation`) + ligne `llm_usage` quand le LLM a répondu, pour
    prouver depuis les logs & la DB que la V3 live passe bien par le
    LLM d'extraction (pas uniquement par le détecteur Python).
    """
    q = (question or "").strip()
    if not q:
        logger.info("intent_llm: path=empty-question")
        return parse_intent(q)

    # Court-circuit salutation / smalltalk sans coût LLM.
    if _QUICK_CONVERSATION.match(q):
        logger.info("intent_llm: path=quick-conversation (zero LLM) q=%r", q[:80])
        return parse_intent(q)

    # LLM disponible ?
    try:
        cfg = get_effective_llm_config(db)
    except LlmCryptoError as exc:
        logger.warning("intent_llm: path=fallback-crypto, cfg indispo: %s", exc)
        return _apply_antifallback(parse_intent(q))

    enabled = cfg.get("enabled") and cfg.get("api_key") and cfg.get("provider") and cfg.get("base_url")
    if not enabled:
        logger.info("intent_llm: path=fallback-disabled (LLM off ou config incomplète)")
        return _apply_antifallback(parse_intent(q))

    ok_budget, spent, cap = check_budget(db, cfg.get("daily_cap_usd"))
    if not ok_budget:
        logger.warning("intent_llm: path=fallback-budget-cap (spent=%.4f$ cap=%.4f$)", spent, cap or 0.0)
        return _apply_antifallback(parse_intent(q))

    # 0.38.0 — Charge les skills actifs pour les exposer au LLM.
    try:
        active_skills = load_active_skills(db)
    except Exception as exc:
        logger.warning("intent_llm: load_active_skills failed (%s), continuer sans skills", exc)
        active_skills = []
    if active_skills:
        logger.info(
            "intent_llm: %d skill(s) actif(s) exposé(s) au LLM: %s",
            len(active_skills), [s.slug for s in active_skills],
        )

    # Appel LLM court et borné, avec extraction des `usage` tokens.
    logger.info("intent_llm: path=llm, calling %s (q=%r)", cfg.get("model"), q[:80])
    try:
        result = call_llm_with_usage(
            db,
            user_question=q,
            context_facts="",  # le prompt système contient tout
            system_prompt=_format_system_prompt(active_skills),
            max_tokens_override=350,
            timeout=15.0,
        )
    except LlmInvocationError as exc:
        logger.warning("intent_llm: path=fallback-llm-error (%s)", exc)
        return _apply_antifallback(parse_intent(q))

    if result is None:
        logger.info("intent_llm: path=fallback-llm-none (config partielle en pleine extraction)")
        return _apply_antifallback(parse_intent(q))

    txt, pt, ct, model = result

    # 0.34.1 — Trace comptable : chaque appel d'extraction LLM apparaît
    # désormais dans `llm_usage` (step=-1 pour distinguer la narration
    # qui utilise step∈[0..N]).
    try:
        cost = log_usage(
            db,
            model=model,
            prompt_tokens=pt,
            completion_tokens=ct,
            conversation_id=conversation_id,
            step=-1,
        )
        db.commit()
        logger.info(
            "intent_llm: path=llm-ok pt=%d ct=%d cost≈%.6f$ txt_len=%d",
            pt, ct, cost, len(txt),
        )
    except Exception as exc:
        # Un échec de logging ne doit JAMAIS casser l'extraction. On note
        # et on continue avec le plan — le vrai signal est le JSON parsé.
        logger.warning("intent_llm: log_usage failed (non-fatal): %s", exc)
        db.rollback()

    if not txt:
        return _apply_antifallback(parse_intent(q))

    data = _parse_llm_json(txt)
    if data is None:
        logger.warning("intent_llm: path=fallback-json-parse")
        return _apply_antifallback(parse_intent(q))

    plan = _to_intent_plan(data, q, active_skills=active_skills)
    if plan is None:
        logger.warning("intent_llm: path=fallback-contract-violation")
        return _apply_antifallback(parse_intent(q))

    logger.info(
        "intent_llm: extracted op=%r metric=%r nc=%s",
        plan.operation, plan.metric_key, plan.needs_clarification,
    )
    return plan
