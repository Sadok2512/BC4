"""Hashage mot de passe (argon2id) + JWT HS256.

Règles :
- Aucun mot de passe en clair n'est jamais loggé, retourné, ni comparé
  autrement que via `argon2.PasswordHasher.verify`.
- La vérification est à **temps constant** par argon2 ; un email inconnu
  déclenche quand même une vérification « bidon » pour éviter la timing
  attack qui distinguerait email inconnu / mauvais mot de passe.
- JWT HS256 avec secret `BC4_JWT_SECRET` obligatoire — l'app refuse de
  démarrer sans. TTL fermé par `BC4_JWT_TTL_MIN`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()

# Hash « bidon » pré-calculé, utilisé quand l'email est inconnu pour
# garantir que la boucle d'auth prend le même temps que pour un email
# connu — anti-timing. Généré au premier appel pour éviter d'imposer un
# coût à l'import.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _ph.hash("dummy-password-for-constant-time-check")
    return _DUMMY_HASH


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """`hashed` peut être None (compte sans hash) : on fait quand même
    une vérif bidon pour conserver le temps constant."""
    target = hashed or _dummy_hash()
    try:
        _ph.verify(target, plain)
        # L'identifiant est bon seulement si le hash cible n'était PAS le dummy.
        return hashed is not None
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        # Toute autre erreur argon2 → échec. On ne log pas le mot de passe.
        return False


def create_token(
    *, user_id: str, role: str, ttl_min: int, secret: str
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl_min)
    payload = {
        "sub": user_id,
        "role": role,
        # NumericDate accepte les fractions. La precision sub-seconde rend
        # toute rotation immédiatement révocatoire, même dans la même seconde.
        "iat": now.timestamp(),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256"), exp


class TokenError(Exception):
    pass


def decode_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("invalid") from e
