"""Budget LLM : estimation coût + plafond journalier + journalisation (0.27.0).

Prix USD par 1k tokens (OpenRouter, octobre 2026). Table hardcodée —
mise à jour manuelle quand les prix évoluent. **Jamais inventé** : si
le modèle n'est pas listé, on utilise un coût safe par défaut
`DEFAULT_PRICING` conservateur (plutôt sur-estimer que sous-estimer).

Le cap `daily_cap_usd` est vérifié AVANT chaque appel LLM. Si atteint,
le moteur refuse l'appel et renvoie un message clair « budget atteint ».
Reset implicite à minuit UTC (via `DATE(created_at) = CURRENT_DATE`).

Discipline :
- Jamais d'identité abonné dans `llm_usage` (log de méta-usage).
- `estimated_cost_usd` est une estimation — à auditer vs la facture
  réelle OpenRouter / provider si écart significatif.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# USD per 1000 tokens — à ré-aligner quand les prix bougent.
# Lectures : https://openrouter.ai/models (prix public)
PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "openai/gpt-4o-mini":           {"input": 0.00015, "output": 0.00060},
    "openai/gpt-4o":                {"input": 0.00250, "output": 0.01000},
    "openai/gpt-4-turbo":           {"input": 0.01000, "output": 0.03000},
    # Anthropic
    "anthropic/claude-3-5-haiku":   {"input": 0.00080, "output": 0.00400},
    "anthropic/claude-3-5-sonnet":  {"input": 0.00300, "output": 0.01500},
    "anthropic/claude-3-haiku":     {"input": 0.00025, "output": 0.00125},
    # Mistral
    "mistralai/mistral-small":      {"input": 0.00020, "output": 0.00060},
    "mistralai/mistral-large":      {"input": 0.00400, "output": 0.01200},
}

# Fallback conservateur si modèle inconnu.
DEFAULT_PRICING = {"input": 0.00300, "output": 0.01500}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Coût USD estimé d'un appel. Si modèle inconnu, prix par défaut
    (sur-estime plutôt que sous-estime pour éviter de rater un cap)."""
    p = PRICING.get(model, DEFAULT_PRICING)
    return (prompt_tokens / 1000.0) * p["input"] + (completion_tokens / 1000.0) * p["output"]


def log_usage(
    db: Session,
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    conversation_id: str | None = None,
    step: int | None = None,
) -> float:
    """Insère une ligne `llm_usage` et retourne le coût estimé."""
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    db.execute(
        text(
            "INSERT INTO llm_usage "
            "(created_at, model, prompt_tokens, completion_tokens, "
            " estimated_cost_usd, conversation_id, step) "
            "VALUES (:ts, :model, :pt, :ct, :cost, :cid, :step)"
        ),
        {
            "ts": datetime.now(timezone.utc),
            "model": model,
            "pt": prompt_tokens,
            "ct": completion_tokens,
            "cost": cost,
            "cid": conversation_id,
            "step": step,
        },
    )
    db.commit()
    return cost


def spent_today_usd(db: Session) -> float:
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS s "
            "FROM llm_usage WHERE DATE(created_at AT TIME ZONE 'UTC') = (CURRENT_DATE AT TIME ZONE 'UTC')::date"
        )
    ).scalar()
    return float(row or 0.0)


def check_budget(db: Session, cap_usd: float | None) -> tuple[bool, float, float | None]:
    """Retourne `(ok, spent, cap)`. `ok=False` ⇒ cap atteint, NE PAS appeler.

    `cap=None` ⇒ pas de cap (comportement 0.26.x).
    """
    if cap_usd is None or cap_usd <= 0:
        return True, 0.0, None
    spent = spent_today_usd(db)
    return (spent < cap_usd), spent, cap_usd


def usage_summary(db: Session) -> dict[str, Any]:
    """Pour l'endpoint admin `/settings/llm/usage`."""
    total = spent_today_usd(db)
    rows = db.execute(
        text(
            "SELECT model, SUM(prompt_tokens) AS pt, SUM(completion_tokens) AS ct, "
            "SUM(estimated_cost_usd) AS cost, COUNT(*) AS calls "
            "FROM llm_usage WHERE DATE(created_at AT TIME ZONE 'UTC') = (CURRENT_DATE AT TIME ZONE 'UTC')::date "
            "GROUP BY model ORDER BY cost DESC"
        )
    ).mappings().all()
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "spent_today_usd": total,
        "by_model": [
            {
                "model": r["model"],
                "prompt_tokens": int(r["pt"] or 0),
                "completion_tokens": int(r["ct"] or 0),
                "estimated_cost_usd": float(r["cost"] or 0.0),
                "calls": int(r["calls"] or 0),
            }
            for r in rows
        ],
    }
