"""LLM settings schemas (0.16.0).

Response schemas never carry the plaintext `api_key`. `api_key_set`
is the derived boolean reflecting DB storage. A caller that needs to
know whether a key is configured gets `true|false` — never the key.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LlmSettings(BaseModel):
    """Response for GET/PUT /settings/llm.

    `api_key_set` is derived from DB storage (True iff a cipher is
    present). The plaintext is NEVER returned.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    base_url: str = ""
    model: str = ""
    enabled: bool = False
    api_key_set: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    updated_at: str | None = None
    # 0.27.0 — Maîtrise des coûts
    model_loop: str = ""
    daily_cap_usd: float | None = None


class LlmSettingsInput(BaseModel):
    """Request body for PUT /settings/llm.

    All fields optional (PATCH-like semantics). To CLEAR the stored
    key, pass `api_key: ""` explicitly — `None` means "untouched".
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None)
    enabled: bool | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    # 0.27.0
    model_loop: str | None = None
    daily_cap_usd: float | None = None


class LlmTestResult(BaseModel):
    """Résultat d'un probe `/settings/llm/test`.

    `ok=True` ⇔ un appel chat completions `max_tokens=1` a abouti.
    `message` porte l'erreur safe (jamais la clé) sinon.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    model: str
    latency_ms: int
    message: str | None = None
