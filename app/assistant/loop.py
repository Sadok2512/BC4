"""Boucle agent avec OpenAI function-calling (0.25.0).

Flow :
1. Système prompt + discover_schema + contexte projet actif.
2. User question.
3. Appel LLM avec `tools=TOOL_SCHEMAS` → le modèle peut planifier des
   `tool_calls`.
4. Pour chaque tool_call : exécution via `dispatch_tool`, résultat
   renvoyé en `tool_message`. Chaque résultat porte un `result_id`.
5. Loop jusqu'à ce que le modèle émette un `content` final (ou MAX_STEPS).
6. Composition de la réponse finale : blocs typés basés sur les
   résultats collectés + verdict de comparabilité éventuel.

Garde-fous :
- MAX_STEPS = 5 — un agent qui boucle est coupé.
- Chaque tool_message garde une référence au result_id pour la
  traçabilité (correctif 1).
- Si le LLM renvoie un chiffre dans son final text qui n'apparaît
  AUCUN result → warning (pas de rejet automatique dans ce lot, mais
  trace serveur pour analyse).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.assistant.budget import check_budget, log_usage
from app.assistant.catalog import discover_schema
from app.assistant.digest import make_digest
from app.assistant.tools import TOOL_SCHEMAS, dispatch_tool
from app.models import Project
from app.services.llm_client import (
    DEFAULT_TIMEOUT_S,
    LlmInvocationError,
    _OPENAI_COMPAT,
    _scrub,
)
from app.services.llm_crypto import LlmCryptoError, get_effective_llm_config


logger = logging.getLogger(__name__)


MAX_STEPS = 5


@dataclass
class AgentRun:
    final_text: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    results_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _system_prompt(project: Project) -> str:
    schema = discover_schema()
    return (
        "Tu es l'Assistant BC4, agent analytique sur une campagne radio "
        "drive-test (logs NMF).\n\n"
        f"PROJET ACTIF : « {project.name} » (id={project.id}).\n\n"
        "RÈGLES ABSOLUES :\n"
        "1. AUCUN chiffre dans ta réponse sans qu'il vienne d'un tool_call "
        "renvoyé par l'un des outils ci-dessous. Pas d'invention, même "
        "plausible.\n"
        "2. Chaque bloc data que tu émets (tableau, histogramme, carte) "
        "doit référencer le `result_id` du résultat qui l'a produit.\n"
        "3. Pour toute comparaison (op vs op, bande vs bande), appelle "
        "`compare_distributions` AVANT de présenter — et affiche le "
        "verdict (COMPARABLE / COMPARABLE_WITH_LIMITATIONS / NOT_COMPARABLE).\n"
        "4. Si un résultat renvoie n=0, dis-le explicitement : « donnée "
        "indisponible pour ce groupe » — ne contourne pas.\n"
        "5. Scope projet implicite : NE JAMAIS passer de project_id ou "
        "project en argument d'un outil — le serveur l'injecte.\n"
        "6. Les corrélations ne sont pas des causalités. Si tu en évoques, "
        "précise-le explicitement.\n\n"
        f"GRAMMAIRE AUTORISÉE (datasets, dimensions, mesures) :\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "FINAL : quand tu as toutes les données nécessaires, émets ta "
        "réponse finale en **texte français simple** (3-6 phrases). Ne "
        "répète pas les valeurs numériques dans le texte — la UI "
        "affichera les tableaux/graphes à partir des result_ids. Ta phrase "
        "doit DÉCRIRE la lecture, pas re-lister les chiffres."
    )


def _tool_call_body(cfg: dict, system_prompt: str, messages: list[dict]) -> dict:
    # 0.27.0 — prompt caching Anthropic (via OpenRouter).
    # Le system prompt est volumineux (catalog + règles) et IDENTIQUE
    # à chaque étape de la boucle. On le marque `cache_control:
    # ephemeral` pour que le provider le cache après le 1er appel.
    # Pour les providers qui ignorent `cache_control` (OpenAI direct
    # sur son endpoint natif), le champ est juste passé en no-op —
    # pas de régression.
    system_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": system_prompt,
            # Marque comme cacheable — OpenRouter route vers l'option
            # Anthropic cache_control appropriée pour les modèles Claude.
            "cache_control": {"type": "ephemeral"},
        }
    ]
    body: dict[str, Any] = {
        # 0.27.0 — model_loop (pas cher) pour la boucle outils.
        # Fallback sur `model` si model_loop vide (déjà géré par
        # get_effective_llm_config).
        "model": cfg.get("model_loop") or cfg["model"],
        "messages": [{"role": "system", "content": system_content}, *messages],
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto",
    }
    if cfg["temperature"] is not None:
        body["temperature"] = cfg["temperature"]
    if cfg["max_tokens"] is not None:
        body["max_tokens"] = cfg["max_tokens"]
    return body


def _call_provider(cfg: dict, body: dict, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    api_key = cfg["api_key"]
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise LlmInvocationError(f"timeout après {timeout}s") from None
    except httpx.HTTPError as exc:
        raise LlmInvocationError(f"erreur réseau: {_scrub(str(exc), api_key)}") from None
    if resp.status_code == 401:
        raise LlmInvocationError("provider refuse les identifiants (401)")
    if resp.status_code == 429:
        raise LlmInvocationError("provider en rate-limit (429)")
    if resp.status_code >= 400:
        raise LlmInvocationError(f"provider HTTP {resp.status_code}")
    try:
        return resp.json()
    except Exception:
        raise LlmInvocationError("réponse provider non-JSON") from None


def run_agent(db: Session, project: Project, question: str, *, conversation_id: str | None = None) -> AgentRun:
    """Boucle agent complète. Retourne `AgentRun`. Jamais 5xx propagé —
    toute erreur est encapsulée dans `AgentRun.error`.

    0.27.0 — Trois leviers coût actifs :
    - **Digest** : les tool_messages renvoyés au LLM sont compactés
      (top_K + stats + result_id) via `make_digest` — jamais les rows
      complètes. La donnée complète reste côté serveur (`collected`).
    - **model_loop** : utilisé pour la boucle outils (défaut moins
      cher que `model`).
    - **Budget** : check `daily_cap_usd` AVANT chaque appel + log
      des tokens + coût estimé après chaque appel.
    - **cache_control ephemeral** sur le system prompt (via
      `_tool_call_body`) pour ne pas re-payer l'entrée à chaque étape.
    """
    try:
        cfg = get_effective_llm_config(db)
    except LlmCryptoError as exc:
        return AgentRun(final_text=None, error=f"config LLM illisible: {exc}")

    if not cfg["enabled"]:
        return AgentRun(final_text=None, error="LLM désactivé")
    if not (cfg["provider"] and cfg["model"] and cfg["api_key"] and cfg["base_url"]):
        return AgentRun(final_text=None, error="config LLM incomplète")
    provider = (cfg["provider"] or "").strip().lower()
    if provider not in _OPENAI_COMPAT:
        return AgentRun(final_text=None, error=f"provider {provider!r} non supporté")

    system_prompt = _system_prompt(project)
    messages: list[dict] = [{"role": "user", "content": question}]
    collected: dict[str, dict[str, Any]] = {}
    all_tool_calls: list[dict] = []
    warnings: list[str] = []
    model_used = cfg.get("model_loop") or cfg["model"]

    for step in range(MAX_STEPS):
        # 0.27.0 — Budget pré-check : si cap atteint, on refuse l'appel
        # avec un message clair (jamais une erreur brute, jamais une
        # réponse inventée).
        ok, spent, cap = check_budget(db, cfg.get("daily_cap_usd"))
        if not ok:
            return AgentRun(
                final_text=None,
                tool_calls=all_tool_calls,
                results_by_id=collected,
                warnings=warnings,
                error=(
                    f"Budget LLM du jour atteint ({spent:.2f} $ / {cap:.2f} $). "
                    "Nouvelle fenêtre à minuit UTC. "
                    "Ajuste `settings_llm.daily_cap_usd` si nécessaire."
                ),
            )

        try:
            data = _call_provider(cfg, _tool_call_body(cfg, system_prompt, messages))
        except LlmInvocationError as exc:
            return AgentRun(final_text=None, error=str(exc), tool_calls=all_tool_calls, results_by_id=collected)

        # 0.27.0 — Journalise l'usage pour le cap journalier + audit.
        usage = (data.get("usage") or {}) if isinstance(data, dict) else {}
        try:
            log_usage(
                db,
                model=model_used,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                conversation_id=conversation_id,
                step=step,
            )
        except Exception as exc:
            # Log usage ne doit JAMAIS casser l'appel LLM. Un warn
            # suffit — le cap sera désynchronisé pour cet appel.
            warnings.append(f"log_usage warning (step={step}): {exc!r}")

        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return AgentRun(final_text=None, error="réponse provider malformée", tool_calls=all_tool_calls, results_by_id=collected)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # Fin de boucle — le modèle a répondu en texte final.
            final_text = (msg.get("content") or "").strip()
            return AgentRun(
                final_text=final_text or None,
                tool_calls=all_tool_calls,
                results_by_id=collected,
                warnings=warnings,
            )

        # Ajoute l'ASSISTANT message avec ses tool_calls (contrat OpenAI).
        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for tc in tool_calls:
            tc_id = tc.get("id") or f"call_{step}_{len(all_tool_calls)}"
            fn = (tc.get("function") or {})
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception:
                args = {}
            result = dispatch_tool(name, args, db=db, project=project)
            rid = result.get("result_id") or f"{name}:{step}"
            # IMPORTANT : la donnée COMPLÈTE reste dans `collected` →
            # compose.py la rend intégralement côté UI (tables, cartes).
            # Le LLM, lui, ne reçoit que le digest.
            collected[rid] = result
            all_tool_calls.append({"id": tc_id, "name": name, "args": args, "result_id": rid})

            # 0.27.0 — Digest compact pour le tool_message LLM.
            digest = make_digest(result, name)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": json.dumps(digest, ensure_ascii=False, default=str),
                }
            )

    warnings.append(f"MAX_STEPS={MAX_STEPS} atteint — l'agent n'a pas conclu, résultats partiels collectés.")
    return AgentRun(final_text=None, tool_calls=all_tool_calls, results_by_id=collected, warnings=warnings)
