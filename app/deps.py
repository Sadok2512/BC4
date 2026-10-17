"""Auth deps (B2 — JWT Bearer).

- `get_current_user` : lit `Authorization: Bearer <jwt>`, décode,
  revérifie la vie du compte en base. 401 si manque/invalide/expiré/désactivé.
- `get_actor` : expose l'acteur sous la forme attendue par les routes B0/B1
  (Actor = login + role en vocabulaire Zod existant). Fait le mapping
  role FR→EN (admin/ingenieur/lecteur → admin/editor/viewer) sans
  refaire la vérif — c'est la même source JWT.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AppUser
from app.schemas.settings import Actor
from app.services.auth import TokenError, decode_token


def with_statement_timeout_60s(db: Session = Depends(get_db)) -> Session:
    """0.48.0 — Pose ``SET LOCAL statement_timeout = '60s'`` sur la
    transaction courante. À attacher aux routers lecture (``/projects/*/kpi``,
    ``/dict``) pour qu'une requête bloquée ne traîne pas éternellement en
    attente d'un lock ou d'un scan dément.

    ``SET LOCAL`` s'applique uniquement à la transaction courante — pas
    de pollution du pool. SQLAlchemy ouvre la transaction au premier
    ``execute``, donc on force l'ouverture ici.
    """
    db.execute(text("SET LOCAL statement_timeout = '60s'"))
    return db

# auto_error=False : on gère nous-mêmes la 401 pour l'uniformiser avec les
# autres erreurs de l'API (`{code, message}` au lieu du HTTPBearer défaut).
_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")

# Mapping canonique FR (DB `app_user.role`) → EN (contrat Zod existant).
ROLE_DB_TO_API: dict[str, str] = {
    "admin": "admin",
    "ingenieur": "editor",
    "lecteur": "viewer",
}


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if creds is None or (creds.scheme or "").lower() != "bearer":
        raise HTTPException(
            401,
            {"code": "UNAUTHENTICATED", "message": "Token requis (Authorization: Bearer)"},
        )
    try:
        payload = decode_token(creds.credentials, settings.jwt_secret)
    except TokenError as e:
        msg = "Token expiré" if str(e) == "expired" else "Token invalide"
        raise HTTPException(401, {"code": "INVALID_TOKEN", "message": msg})
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, {"code": "INVALID_TOKEN", "message": "Token mal formé"})
    user = db.get(AppUser, sub)
    if not user or not user.active:
        raise HTTPException(401, {"code": "INVALID_TOKEN", "message": "Compte invalide"})
    return user


def get_actor(current: AppUser = Depends(get_current_user)) -> Actor:
    api_role = ROLE_DB_TO_API.get(current.role)
    if api_role not in {"admin", "editor", "viewer"}:
        # Mapping manquant → écart défaillant, pas silencieux.
        raise HTTPException(
            500, {"code": "ROLE_MAPPING_ERROR", "message": f"Rôle inconnu : {current.role}"}
        )
    return Actor(login=current.email, role=api_role)  # type: ignore[arg-type]


def require_role(actor: Actor, *allowed: str) -> None:
    if actor.role not in allowed:
        raise HTTPException(403, {"code": "FORBIDDEN", "message": "Permission refusée"})
