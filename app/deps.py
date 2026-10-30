"""Auth deps (B2 — JWT Bearer).

- `get_current_user` : lit `Authorization: Bearer <jwt>`, décode,
  revérifie la vie du compte en base. 401 si manque/invalide/expiré/désactivé.
- `get_actor` : expose l'acteur sous la forme attendue par les routes B0/B1
  (Actor = login + role en vocabulaire Zod existant). Fait le mapping
  role FR→EN (admin/ingenieur/lecteur → admin/editor/viewer) sans
  refaire la vérif — c'est la même source JWT.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AppUser, Project, ProjectShare
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
    request: Request,
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
    issued_at = payload.get("iat")
    if user.password_changed_at is not None:
        changed_at = user.password_changed_at
        if changed_at.tzinfo is None:
            from datetime import timezone
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        if not isinstance(issued_at, (int, float)) or float(issued_at) < changed_at.timestamp():
            raise HTTPException(
                401,
                {"code": "TOKEN_REVOKED", "message": "Token antérieur au changement de mot de passe"},
            )
    if user.must_change_password and request.url.path != "/auth/change-password":
        raise HTTPException(
            403,
            {"code": "PASSWORD_CHANGE_REQUIRED", "message": "Changement de mot de passe requis"},
        )
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


def _project_not_found() -> HTTPException:
    return HTTPException(404, {"code": "NOT_FOUND", "message": "Projet introuvable"})


def get_accessible_project(
    request: Request,
    current: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project | None:
    """Resolve the route project and hide inaccessible private projects.

    Project listing/creation have no project path parameter and are scoped by
    their handlers.  Evidence results resolve their project through task_result.
    There is deliberately no administrator bypass.
    """
    project_id = request.path_params.get("project_id")
    if project_id is None and request.url.path.startswith("/results/"):
        result_id = request.path_params.get("result_id")
        project_id = db.execute(
            text("SELECT project_id FROM task_result WHERE id=:result_id"),
            {"result_id": result_id},
        ).scalar_one_or_none()
        if project_id is None:
            raise _project_not_found()
    if project_id is None:
        return None
    project = db.get(Project, project_id)
    shared = False
    if project is not None and project.owner_id != current.id and project.visibility != "public":
        shared = (
            db.query(ProjectShare)
            .filter(ProjectShare.project_id == project.id, ProjectShare.user_id == current.id)
            .first()
            is not None
        )
    if project is None or (
        project.owner_id != current.id and project.visibility != "public" and not shared
    ):
        raise _project_not_found()
    return project


def require_project_write(
    request: Request,
    project: Project | None = Depends(get_accessible_project),
    current: AppUser = Depends(get_current_user),
) -> Project | None:
    """Allow project mutations to the owner only, including administrators."""
    if request.method in {"GET", "HEAD", "OPTIONS"} or project is None:
        return project
    if project.owner_id != current.id:
        raise _project_not_found()
    return project
