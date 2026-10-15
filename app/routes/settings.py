import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import ROLE_DB_TO_API, get_actor, require_role
from app.models import (
    AiConfigRow,
    ApiPermissionsRow,
    AppearanceRow,
    AppUser,
    GeoReference,
    KpiCatalogItem,
    OrganizationRow,
    PasswordPolicyRow,
    User,
)
from app.schemas.settings import (
    About,
    Actor,
    AiConfig,
    AiConnection,
    Appearance,
    ApiPermissions,
    GeoReference as GeoRefSchema,
    Kpi,
    KpiCatalogResponse,
    Organization,
    OrganizationLimits,
    PasswordPolicy,
    User as UserSchema,
    UserCreate,
    UsersResponse,
)
from app.services.auth import hash_password


# Reverse mapping Zod (admin|editor|viewer) → DB FR (admin|ingenieur|lecteur)
# pour la création d'utilisateur. Centralisé pour aligner avec `deps.ROLE_DB_TO_API`.
ROLE_API_TO_DB = {v: k for k, v in ROLE_DB_TO_API.items()}


def _check_password_policy(password: str, policy: PasswordPolicyRow) -> list[str]:
    """Renvoie la liste des règles violées. Vide = conforme."""
    problems: list[str] = []
    if len(password) < policy.min_length:
        problems.append(f"au moins {policy.min_length} caractères (actuellement {len(password)})")
    if policy.require_digit and not any(c.isdigit() for c in password):
        problems.append("au moins un chiffre")
    if policy.require_upper and not any(c.isupper() for c in password):
        problems.append("au moins une majuscule")
    return problems

router = APIRouter(prefix="/settings", tags=["settings"])


def _user_schema(u: User) -> UserSchema:
    return UserSchema(
        id=u.id,
        login=u.login,
        display_name=u.display_name,
        role=u.role,  # type: ignore[arg-type]
        active=u.active,
        created_at=u.created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        last_login_at=u.last_login_at.replace(microsecond=0).isoformat().replace("+00:00", "Z") if u.last_login_at else None,
    )


# ----- Appearance -----
@router.get("/appearance", response_model=Appearance)
def get_appearance(db: Session = Depends(get_db)) -> Appearance:
    row = db.query(AppearanceRow).one()
    return Appearance(org_primary_hex=row.org_primary_hex)


# ----- Organization -----
@router.get("/organization", response_model=Organization)
def get_organization(db: Session = Depends(get_db)) -> Organization:
    row = db.query(OrganizationRow).one()
    return Organization(
        name=row.name,
        short_name=row.short_name,
        description=row.description,
        logo_data_url=row.logo_data_url,
        admin_contact=row.admin_contact,
        domain=row.domain,
        show_in_header=row.show_in_header,
        show_in_exports=row.show_in_exports,
        limits=OrganizationLimits(
            name_max=row.name_max,
            logo_max_bytes=row.logo_max_bytes,
            logo_types=row.logo_types,
        ),
    )


# ----- About (public) -----
@router.get("/about", response_model=About)
def get_about(db: Session = Depends(get_db)) -> About:
    org_row = db.query(OrganizationRow).one()
    return About(
        version="0.1.0",
        build_number=None,
        build_date=None,
        environment="development",
        api_contracts_version="bc4-back/0.1.0",
        api_client_status="live",
        organization=org_row.name or None,
        license=None,
    )


# ----- Users (seeded read-only in B0; mutations déclarées en écart ouvert) -----
@router.get("/users", response_model=UsersResponse)
def get_users(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> UsersResponse:
    require_role(actor, "admin", "editor")
    users = [_user_schema(u) for u in db.query(User).order_by(User.created_at).all()]
    policy_row = db.query(PasswordPolicyRow).one()
    perms_row = db.query(ApiPermissionsRow).one()
    return UsersResponse(
        users=users,
        policy=PasswordPolicy(
            min_length=policy_row.min_length,
            require_digit=policy_row.require_digit,
            require_upper=policy_row.require_upper,
        ),
        permissions=ApiPermissions(
            editor_can_edit_geo=perms_row.editor_can_edit_geo,
            editor_can_edit_kpi=perms_row.editor_can_edit_kpi,
        ),
    )


@router.post("/users", response_model=UserSchema, status_code=201)
def create_user(
    body: UserCreate,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> UserSchema:
    """Crée un compte (B2) : admin requis, policy mdp appliquée côté serveur.
    Le compte est écrit à la fois dans `app_user` (source d'auth JWT) et
    dans `users` (affichage settings). Role mappé Zod → DB FR via
    `ROLE_API_TO_DB`. Mdp hashé argon2id, jamais stocké en clair ni loggé."""
    require_role(actor, "admin")

    # Policy serveur — jamais tolérée par défaut, violations rendues à l'utilisateur.
    policy = db.query(PasswordPolicyRow).one()
    if body.password != body.password_confirm:
        raise HTTPException(
            422,
            {
                "code": "VALIDATION",
                "message": "La confirmation du mot de passe ne correspond pas.",
                "field": "password_confirm",
            },
        )
    problems = _check_password_policy(body.password, policy)
    if problems:
        raise HTTPException(
            422,
            {
                "code": "WEAK_PASSWORD",
                "message": "Mot de passe non conforme : " + ", ".join(problems) + ".",
                "field": "password",
                "policy": {
                    "min_length": policy.min_length,
                    "require_digit": policy.require_digit,
                    "require_upper": policy.require_upper,
                },
            },
        )

    login = body.login.strip()
    display_name = body.display_name.strip()
    if not login or not display_name:
        raise HTTPException(422, {"code": "VALIDATION", "message": "login + display_name requis"})

    # Email est utilisé comme identifiant d'auth. Si `login` ressemble à un
    # email, on l'utilise ; sinon on compose `login@bc4.local`.
    email = login.lower() if "@" in login else f"{login.lower()}@bc4.local"
    existing_app = db.query(AppUser).filter(AppUser.email == email).one_or_none()
    existing_u = db.query(User).filter(User.login == login).one_or_none()
    if existing_app or existing_u:
        raise HTTPException(409, {"code": "CONFLICT", "message": "Cet identifiant existe déjà.", "field": "login"})

    db_role = ROLE_API_TO_DB.get(body.role)
    if db_role is None:
        raise HTTPException(422, {"code": "VALIDATION", "message": f"Rôle inconnu : {body.role}"})

    now = datetime.now(timezone.utc)
    hashed = hash_password(body.password)

    # 1) app_user (source d'auth)
    app_u = AppUser(
        id=f"u-{uuid.uuid4().hex[:12]}",
        email=email,
        password_hash=hashed,
        role=db_role,
        active=True,
        created_at=now,
    )
    db.add(app_u)
    # 2) users (vue settings)
    u = User(
        id=app_u.id,
        login=login,
        display_name=display_name,
        role=body.role,  # Zod vocab pour la réponse `/settings/users`
        active=True,
        created_at=now,
        last_login_at=None,
        password_hash=None,  # jamais stocké ici — l'auth passe par app_user
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return _user_schema(u)


# ----- Geography (seeded read-only) -----
@router.get("/geo", response_model=list[GeoRefSchema])
def get_geo_references(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> list[GeoRefSchema]:
    require_role(actor, "admin", "editor")
    rows = db.query(GeoReference).order_by(GeoReference.version.desc()).all()
    return [
        GeoRefSchema(
            id=r.id, version=r.version, filename=r.filename, imported_at=r.imported_at,
            author=r.author, status=r.status, rows=r.rows,
        )
        for r in rows
    ]


@router.post("/geo/import", status_code=501)
def geo_import(actor: Actor = Depends(get_actor)) -> dict:
    raise HTTPException(501, {
        "code": "NOT_IMPLEMENTED",
        "message": "Import géo — écart ouvert B0 (voir CHANGELOG)",
    })


# ----- KPI catalog settings -----
@router.get("/kpi", response_model=KpiCatalogResponse)
def get_kpi_catalog_settings(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> KpiCatalogResponse:
    require_role(actor, "admin", "editor")
    items = [
        Kpi(
            code=k.code, name=k.name, description=k.description, family=k.family,
            tech=k.tech, unit=k.unit, formula=k.formula, status=k.status,  # type: ignore[arg-type]
            version=k.version, source_events=k.source_events, history=k.history,
        )
        for k in db.query(KpiCatalogItem).order_by(KpiCatalogItem.code).all()
    ]
    return KpiCatalogResponse(
        items=items,
        statuses=["draft", "validated", "published", "archived"],
        formula_engine=None,
    )


@router.post("/kpi", status_code=501)
def create_kpi(actor: Actor = Depends(get_actor)) -> dict:
    raise HTTPException(501, {
        "code": "NOT_IMPLEMENTED",
        "message": "CRUD KPI — écart ouvert B0 (voir CHANGELOG)",
    })


# ----- AI config (read-only in B0) -----
@router.get("/ai/enabled")
def get_ai_enabled(db: Session = Depends(get_db)) -> bool:
    row = db.query(AiConfigRow).one()
    return row.enabled


@router.get("/ai", response_model=AiConfig)
def get_ai_config(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> AiConfig:
    require_role(actor, "admin")
    row = db.query(AiConfigRow).one()
    return AiConfig(
        enabled=row.enabled,
        endpoint_url=row.endpoint_url,
        model_code=row.model_code,
        provider=row.provider,
        providers=row.providers,
        auth_method=row.auth_method,  # type: ignore[arg-type]
        has_secret=row.has_secret,
        config_version=row.config_version,
        saved_at=row.saved_at,
        connection=AiConnection(
            status=row.connection.get("status", "untested"),  # type: ignore[arg-type]
            tested_at=row.connection.get("tested_at"),
            message=row.connection.get("message"),
        ),
    )


@router.put("/ai", status_code=501)
def put_ai_config(actor: Actor = Depends(get_actor)) -> dict:
    raise HTTPException(501, {
        "code": "NOT_IMPLEMENTED",
        "message": "Config IA — écart ouvert B0 (voir CHANGELOG)",
    })
