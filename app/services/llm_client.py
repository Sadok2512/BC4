"""LLM HTTP client (0.17.0).

Appel du provider LLM configuré (via `settings_llm` ou env). Format
d'échange : **chat completions compatible OpenAI** (de facto standard —
fonctionne avec OpenAI, Mistral, Together, Groq, ou tout proxy
OpenAI-compat). Un provider non-compatible OpenAI est rejeté avec un
message explicite (pas d'invention de wire format).

Garanties :
- La clé en clair est lue via `decrypt_key` dans la même frame que
  l'appel HTTP, passée dans `Authorization: Bearer` et JAMAIS loggée.
- Toute `Exception` est capturée par la route appelante — le client
  lève `LlmInvocationError` avec un message **safe** (jamais la clé
  dans le `str(exc)`, scrub systématique).
- Pas de retry silencieux : la UI préfère un claim « indisponible » à
  un affichage figé.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.services.llm_crypto import LlmCryptoError, get_effective_llm_config


logger = logging.getLogger(__name__)


class LlmInvocationError(RuntimeError):
    """Erreur d'appel LLM. Le message est safe à afficher (pas de secret)."""


# Timeout court volontairement : l'assistant doit répondre vite. Si le
# LLM est lent, on bascule en UNAVAILABLE plutôt qu'attendre.
DEFAULT_TIMEOUT_S = 12.0

# Providers reconnus (format wire). Les autres passent par le défaut
# OpenAI-compat (base_url + /chat/completions). On N'INVENTE PAS de
# wire format pour un provider inconnu — l'utilisateur doit pointer un
# endpoint OpenAI-compat.
_OPENAI_COMPAT = {"openai", "mistral", "together", "groq", "openrouter", "custom", ""}


def _scrub(text: str, secret: str) -> str:
    """Remplace la clé en clair dans un message d'erreur avant log/retour."""
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


_DEFAULT_ANALYSIS_SYSTEM_PROMPT = (
    "Tu es l'assistant BC4 pour un benchmark radio télécom. "
    "Tu ne cites AUCUN chiffre qui n'apparaît pas explicitement dans le "
    "contexte factuel ci-dessous. Si une donnée manque, dis-le "
    "(« données insuffisantes »), ne l'invente JAMAIS. "
    "Réponds en français, 4 phrases max, ton technique sobre."
)


def call_llm(
    db: Session,
    user_question: str,
    context_facts: str,
    *,
    system_prompt: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_tokens_override: int | None = None,
) -> str | None:
    """Appelle le LLM effectif. Retourne le texte généré, ou `None` si
    la config est incomplète / désactivée (pas une erreur — l'appelant
    doit alors émettre un claim UNAVAILABLE « LLM non configuré »).

    Lève `LlmInvocationError` sur erreur réseau / provider — l'appelant
    doit la convertir en claim UNAVAILABLE sans propager de 5xx.
    """
    try:
        cfg = get_effective_llm_config(db)
    except LlmCryptoError as exc:
        # Clé en DB illisible (ex : BC4_LLM_SECRET_KEY changé).
        raise LlmInvocationError(f"config LLM illisible: {exc}") from None

    if not cfg["enabled"]:
        return None
    if not (cfg["provider"] and cfg["model"] and cfg["api_key"] and cfg["base_url"]):
        return None

    provider = (cfg["provider"] or "").strip().lower()
    if provider not in _OPENAI_COMPAT:
        raise LlmInvocationError(
            f"provider '{cfg['provider']}' non supporté — endpoint OpenAI-compat requis"
        )

    api_key: str = cfg["api_key"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    system_msg = system_prompt or _DEFAULT_ANALYSIS_SYSTEM_PROMPT
    # Si pas de context_facts (ex: mode CONVERSATION ou intent classifier),
    # on envoie juste la question — pas de bloc « Contexte factuel : (vide) »
    # qui perturberait le modèle.
    user_msg = (
        f"Contexte factuel (source DB, immuable):\n{context_facts}\n\n"
        f"Question utilisateur: {user_question}"
        if context_facts
        else user_question
    )

    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }
    if cfg["temperature"] is not None:
        body["temperature"] = cfg["temperature"]
    # Un `max_tokens_override` (ex: probe = 1) écrase le réglage DB —
    # on NE combine pas, on remplace, pour que le probe reste prévisible
    # quel que soit l'état de `settings_llm.max_tokens`.
    effective_max_tokens = (
        max_tokens_override if max_tokens_override is not None else cfg["max_tokens"]
    )
    if effective_max_tokens is not None:
        body["max_tokens"] = effective_max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise LlmInvocationError(f"timeout après {timeout}s") from None
    except httpx.HTTPError as exc:
        raise LlmInvocationError(
            f"erreur réseau: {_scrub(str(exc), api_key)}"
        ) from None

    if resp.status_code == 401:
        raise LlmInvocationError("provider refuse les identifiants (401)")
    if resp.status_code == 429:
        raise LlmInvocationError("provider en rate-limit (429)")
    if resp.status_code >= 400:
        # On n'inclut PAS le body de l'erreur (il peut contenir des
        # headers reflétés / tokens). Juste le code.
        raise LlmInvocationError(f"provider HTTP {resp.status_code}")

    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise LlmInvocationError("réponse provider malformée") from None

    if not isinstance(text, str) or not text.strip():
        raise LlmInvocationError("réponse provider vide")
    return text.strip()


def probe_llm(db: Session, *, timeout: float = 10.0) -> tuple[bool, str, int, str | None]:
    """Probe « ping » du LLM configuré : chat completion `max_tokens=1`.

    Retourne `(ok, model, latency_ms, err_message)`. Jamais 5xx, jamais
    de clé dans `err_message` (scrub via `_scrub` dans `call_llm`).

    - `enabled=false` ou config incomplète → `(False, model, 0, "…")`.
    - Erreur réseau/provider → `(False, model, latency_ms, "<message safe>")`.
    - Succès (texte non vide reçu) → `(True, model, latency_ms, None)`.
    """
    import time

    cfg = get_effective_llm_config(db)
    model = cfg.get("model", "") or ""

    if not cfg["enabled"]:
        return False, model, 0, "LLM désactivé — activez-le dans /settings/llm."
    if not (cfg["provider"] and cfg["model"] and cfg["api_key"] and cfg["base_url"]):
        return False, model, 0, "Config LLM incomplète (provider/base_url/model/api_key)."

    t0 = time.monotonic()
    try:
        text = call_llm(
            db,
            user_question="ping",
            context_facts="Probe de connectivité. Réponds strictement 'ok'.",
            timeout=timeout,
            max_tokens_override=1,
        )
    except LlmInvocationError as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return False, model, latency_ms, str(exc)

    latency_ms = int((time.monotonic() - t0) * 1000)
    if not text:
        # `call_llm` renverrait None uniquement si enabled=false ou config
        # incomplète — déjà traité au-dessus. Belt-and-braces.
        return False, model, latency_ms, "Réponse vide du provider."
    return True, model, latency_ms, None


# ---------------------------------------------------------------------------
# 0.23.1 — Classification d'intention (CONVERSATION vs ANALYSE).
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "Classifie la question suivante en 1 mot EXACT, sans ponctuation ni autre texte : "
    "'CONVERSATION' si c'est une salutation, 'qui es-tu', 'comment tu marches', "
    "smalltalk, remerciement ; "
    "'ANALYSE' si c'est une demande de chiffre, liste, paramètre technique, "
    "carte, comparaison, KPI, message RRC, opérateur, bande. "
    "Réponds UNIQUEMENT par 'CONVERSATION' ou 'ANALYSE'."
)


def call_llm_classify(db: Session, question: str) -> str | None:
    """Appel LLM dédié à la classification d'intention. Max 5 tokens,
    timeout court. Retourne la chaîne brute (parsing laissé à l'appelant)
    ou `None` si LLM désactivé/indisponible — l'appelant choisit alors
    un défaut safe (généralement ANALYSE pour préserver le comportement
    existant)."""
    try:
        return call_llm(
            db,
            user_question=question,
            context_facts="",
            system_prompt=_CLASSIFY_SYSTEM_PROMPT,
            max_tokens_override=5,
            timeout=5.0,
        )
    except LlmInvocationError:
        # Toute erreur réseau/provider → None, l'appelant tombe sur son
        # défaut (ANALYSE). Pas de 5xx propagé.
        return None


def _conversation_system_prompt(project_name: str) -> str:
    return (
        "Tu es l'Assistant BC4 pour un benchmark radio télécom. "
        "Mode CONVERSATION. "
        f"Le projet actif est : « {project_name} ». "
        "Réponds brièvement (2-3 phrases max), en français, ton sobre. "
        "NE CITE AUCUN CHIFFRE, AUCUNE donnée métier (opérateurs, bandes, "
        "messages RRC, KPI, débit, RSRP) — ces informations relèvent du mode "
        "ANALYSE qui est un autre chemin de code. "
        "Si l'utilisateur te demande qui tu es, ce que tu fais, ou comment "
        "tu marches, présente-toi avec ce texte (adapte uniquement le nom du "
        f"projet) : « Bonjour, je suis l'assistant BC4. Je réponds à partir "
        f"des données du projet actif ({project_name}) : dictionnaire RRC, "
        f"mesures, KPI, cartes, et stratégie de mobilité / timers / contrôle "
        f"de puissance. Chaque chiffre que je donne est sourcé. "
        f"Que veux-tu analyser ? ». "
        "Si c'est une salutation simple, salue en retour et invite à poser "
        "une question d'analyse. "
        "Si c'est un remerciement ou un au revoir, réponds poliment en 1 phrase."
    )


def call_llm_conversation(
    db: Session, question: str, project_name: str, *, timeout: float = 10.0
) -> str | None:
    """Appel LLM en mode CONVERSATION. Pas de contexte factuel métier
    (le prompt système interdit tout chiffre). Retourne le texte ou
    `None` si LLM désactivé/incomplet. Lève `LlmInvocationError` sur
    erreur réseau/provider — l'appelant doit convertir en UNAVAILABLE."""
    return call_llm(
        db,
        user_question=question,
        context_facts="",
        system_prompt=_conversation_system_prompt(project_name),
        timeout=timeout,
    )
