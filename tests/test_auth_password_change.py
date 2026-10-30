from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest
from app.services.auth import create_token, decode_token, hash_password, verify_password


def test_change_password_requires_twelve_characters() -> None:
    with pytest.raises(ValidationError):
        ChangePasswordRequest(old_password="old", new_password="too-short")


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("test-password-long")
    assert hashed.startswith("$argon2id$")
    assert verify_password("test-password-long", hashed)
    assert not verify_password("wrong-password", hashed)


def test_token_iat_has_rotation_precision() -> None:
    token, _ = create_token(
        user_id="auth-test-user",
        role="admin",
        ttl_min=5,
        secret="auth-test-secret",
    )
    payload = decode_token(token, "auth-test-secret")
    assert isinstance(payload["iat"], float)
    assert payload["iat"] <= datetime.now(timezone.utc).timestamp()
