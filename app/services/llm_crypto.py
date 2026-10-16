"""LLM config persistence crypto helpers (0.16.0).

Fernet symmetric encryption of the LLM `api_key` at rest. The key is
stored in `settings_llm.api_key_cipher` as a base64 blob and is NEVER
exposed in cleartext over the API nor through logs. Call sites must
only read the plaintext via `decrypt_key` and immediately pass it to
the LLM HTTP client — never keep it in request/response bodies.

Precedence rule (consumed by `/assistant`):
  DB (`settings_llm`) > env (`BC4_LLM_*`)

A missing `BC4_LLM_SECRET_KEY` is tolerated for READ (the UI can show
`api_key_set: true|false` without decrypting); it is REFUSED for
WRITE — otherwise we'd be stashing an opaque blob with no key, which
is just cleartext in disguise.
"""

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LlmSettingsRow


class LlmCryptoError(RuntimeError):
    """Raised when the Fernet key is missing/invalid for a WRITE op."""


def _fernet() -> Fernet:
    key = settings.llm_secret_key
    if not key:
        raise LlmCryptoError(
            "BC4_LLM_SECRET_KEY manquant — impossible de chiffrer la clé LLM."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # invalid base64 / wrong length
        raise LlmCryptoError(f"BC4_LLM_SECRET_KEY invalide: {exc}") from exc


def encrypt_key(plain: str) -> str:
    """Encrypt a plaintext API key. Returns a base64 cipher string.

    Caller must ensure `plain` is non-empty. An empty string means
    "clear the stored key" (handled by routes, not here).
    """
    if not plain:
        raise LlmCryptoError("api_key vide — rien à chiffrer")
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_key(cipher: str | None) -> str | None:
    """Decrypt a cipher back to plaintext. Returns None if no cipher.

    Raises `LlmCryptoError` if the Fernet key is missing or the token
    cannot be decrypted — fail fast rather than silently returning a
    broken key to the LLM client.
    """
    if not cipher:
        return None
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken as exc:
        raise LlmCryptoError(
            "api_key chiffrée illisible — vérifier BC4_LLM_SECRET_KEY"
        ) from exc


def get_row(db: Session) -> LlmSettingsRow:
    """Return the singleton row (id=1), creating it if the seed row
    went missing. Migration 0009 inserts it, so this is a safety net."""
    row = db.get(LlmSettingsRow, 1)
    if row is None:
        row = LlmSettingsRow(id=1)
        db.add(row)
        db.flush()
    return row


def get_effective_llm_config(db: Session) -> dict[str, Any]:
    """Compute the effective LLM config consumed by `/assistant`.

    Precedence: DB fields (`settings_llm`) override env (`BC4_LLM_*`).
    A field is considered "set" by the DB when it's non-empty — empty
    string falls back to env so a half-filled DB row doesn't shadow a
    working env config.

    `api_key` is returned in cleartext ONLY in this function's result
    (meant to be handed directly to the LLM HTTP client in the same
    stack frame). It is NEVER serialized to a response schema.
    """
    row = get_row(db)
    env = settings

    def pick(db_val: str, env_val: str) -> str:
        return db_val if db_val else env_val

    api_key = decrypt_key(row.api_key_cipher) if row.api_key_cipher else None
    if not api_key:
        api_key = env.llm_api_key or ""

    # `enabled` is a bool, no "empty" fallback — DB wins outright. The
    # env flag only kicks in when the DB row has never been toggled;
    # here we treat the migration default (False) as "unset" and let
    # env override. That's what the user asked for: env is a fallback.
    enabled = row.enabled if row.enabled else bool(env.llm_enabled)

    # 0.27.0 — model_loop (fallback: env, puis `model`). daily_cap_usd.
    model_main = pick(row.model, env.llm_model)
    model_loop = pick(
        row.model_loop or "",
        env.llm_model_loop or "",
    ) or model_main  # fallback ultime : même modèle que `model`
    daily_cap = row.daily_cap_usd
    if daily_cap is None and env.llm_daily_cap_usd > 0:
        daily_cap = float(env.llm_daily_cap_usd)
    return {
        "provider": pick(row.provider, env.llm_provider),
        "base_url": pick(row.base_url, env.llm_base_url),
        "model": model_main,
        "model_loop": model_loop,
        "api_key": api_key,
        "enabled": enabled,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "daily_cap_usd": daily_cap,
    }
