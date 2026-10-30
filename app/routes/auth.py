from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser
from app.schemas.auth import ChangePasswordRequest, LoginRequest, LoginResponse, PublicUser
from app.services.auth import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(u: AppUser) -> PublicUser:
    return PublicUser(
        id=u.id,
        email=u.email,
        role=u.role,  # type: ignore[arg-type]
        active=u.active,
        created_at=u.created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        must_change_password=u.must_change_password,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """401 franc, pas de distinction email inconnu / mauvais mot de passe.
    `verify_password` est en temps constant même quand le hash est absent
    (dummy hash) — anti-timing."""
    user = (
        db.query(AppUser)
        .filter(AppUser.email == body.email.lower())
        .one_or_none()
    )
    hashed = user.password_hash if user else None
    ok = verify_password(body.password, hashed)
    if not ok or not user or not user.active:
        raise HTTPException(
            401, {"code": "INVALID_CREDENTIALS", "message": "Identifiants invalides"}
        )
    token, exp = create_token(
        user_id=user.id,
        role=user.role,
        ttl_min=settings.jwt_ttl_min,
        secret=settings.jwt_secret,
    )
    return LoginResponse(
        token=token,
        expires_at=exp.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        user=_public(user),
    )


@router.post("/change-password", response_model=LoginResponse)
def change_password(
    body: ChangePasswordRequest,
    current: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoginResponse:
    if not verify_password(body.old_password, current.password_hash):
        raise HTTPException(
            400,
            {"code": "INVALID_CURRENT_PASSWORD", "message": "Ancien mot de passe incorrect"},
        )
    if body.old_password == body.new_password:
        raise HTTPException(
            400,
            {"code": "PASSWORD_UNCHANGED", "message": "Le nouveau mot de passe doit être différent"},
        )
    current.password_hash = hash_password(body.new_password)
    current.must_change_password = False
    current.password_changed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current)
    token, exp = create_token(
        user_id=current.id,
        role=current.role,
        ttl_min=settings.jwt_ttl_min,
        secret=settings.jwt_secret,
    )
    return LoginResponse(
        token=token,
        expires_at=exp.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        user=_public(current),
    )


@router.post("/logout", status_code=204)
def logout(current: AppUser = Depends(get_current_user)) -> None:
    """Stateless JWT : la purge du token est côté client. L'appel sert à
    vérifier que le token était valide avant la purge (sinon 401)."""
    return None


@router.get("/me", response_model=PublicUser)
def me(current: AppUser = Depends(get_current_user)) -> PublicUser:
    return _public(current)
