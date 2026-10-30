import uuid
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings

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
    UserCreated,
    UsersResponse,
)
from app.schemas.llm import LlmSettings, LlmSettingsInput, LlmTestResult
from app.services.auth import hash_password
from app.services.llm_client import probe_llm
from app.services.llm_crypto import LlmCryptoError, encrypt_key, get_row


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
        environment=settings.env,
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


@router.post("/users", response_model=UserCreated, status_code=201)
def create_user(
    body: UserCreate,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> UserCreated:
    """Crée un compte (B2) : admin requis, policy mdp appliquée côté serveur.
    Le compte est écrit à la fois dans `app_user` (source d'auth JWT) et
    dans `users` (affichage settings). Role mappé Zod → DB FR via
    `ROLE_API_TO_DB`. Mdp hashé argon2id, jamais stocké en clair ni loggé."""
    require_role(actor, "admin")

    # Policy serveur — jamais tolérée par défaut, violations rendues à l'utilisateur.
    policy = db.query(PasswordPolicyRow).one()
    generated_password = None
    password = body.password
    if password is None:
        generated_password = secrets.token_urlsafe(max(12, policy.min_length)) + "A1"
        password = generated_password
    if body.password is not None and body.password != body.password_confirm:
        raise HTTPException(
            422,
            {
                "code": "VALIDATION",
                "message": "La confirmation du mot de passe ne correspond pas.",
                "field": "password_confirm",
            },
        )
    problems = _check_password_policy(password, policy)
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
    hashed = hash_password(password)

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
    return UserCreated(**_user_schema(u).model_dump(), initial_password=generated_password)


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


# ----- LLM config (0.16.0) -----
# Admin-only. `api_key` chiffrée au repos (Fernet) ; jamais renvoyée
# en clair, jamais loggée. GET expose `api_key_set` (bool) uniquement.
def _llm_response(row) -> LlmSettings:
    return LlmSettings(
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        enabled=row.enabled,
        api_key_set=bool(row.api_key_cipher),
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        updated_at=row.updated_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if row.updated_at
        else None,
        model_loop=row.model_loop or "",
        daily_cap_usd=row.daily_cap_usd,
    )


@router.get("/llm", response_model=LlmSettings)
def get_llm_settings(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> LlmSettings:
    require_role(actor, "admin")
    return _llm_response(get_row(db))


@router.put("/llm", response_model=LlmSettings)
def put_llm_settings(
    body: LlmSettingsInput,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> LlmSettings:
    require_role(actor, "admin")
    row = get_row(db)

    if body.provider is not None:
        row.provider = body.provider.strip()
    if body.base_url is not None:
        row.base_url = body.base_url.strip()
    if body.model is not None:
        row.model = body.model.strip()
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.temperature is not None:
        row.temperature = body.temperature
    if body.max_tokens is not None:
        row.max_tokens = body.max_tokens
    # 0.27.0 — maîtrise des coûts
    if body.model_loop is not None:
        row.model_loop = body.model_loop.strip() or None
    if body.daily_cap_usd is not None:
        row.daily_cap_usd = body.daily_cap_usd

    # api_key: None = untouched, "" = clear, non-empty = encrypt + store.
    if body.api_key is not None:
        if body.api_key == "":
            row.api_key_cipher = None
        else:
            try:
                row.api_key_cipher = encrypt_key(body.api_key)
            except LlmCryptoError as exc:
                # Fail fast rather than storing cleartext in disguise.
                raise HTTPException(
                    400,
                    {"code": "LLM_CRYPTO", "message": str(exc), "field": "api_key"},
                ) from exc

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _llm_response(row)


@router.get("/llm/usage")
def get_llm_usage(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> dict:
    """0.27.0 — Dépense LLM du jour UTC + breakdown par modèle.

    Admin-only. Retourne `{date, spent_today_usd, by_model[...]}`.
    Les coûts sont ESTIMÉS (table PRICING en code) — à auditer vs la
    facture provider si écart.
    """
    require_role(actor, "admin")
    from app.assistant.budget import usage_summary
    summary = usage_summary(db)
    row = get_row(db)
    summary["cap_usd"] = row.daily_cap_usd
    if row.daily_cap_usd:
        summary["remaining_usd"] = max(0.0, row.daily_cap_usd - summary["spent_today_usd"])
    else:
        summary["remaining_usd"] = None
    return summary


@router.post("/llm/test", response_model=LlmTestResult)
def test_llm_connection(
    actor: Actor = Depends(get_actor), db: Session = Depends(get_db)
) -> LlmTestResult:
    """Probe la config LLM courante : un chat completion `max_tokens=1`.
    Admin-only. Jamais 5xx (le détail d'échec est dans `message`,
    jamais la clé en clair)."""
    require_role(actor, "admin")
    ok, model, latency_ms, err = probe_llm(db)
    return LlmTestResult(ok=ok, model=model, latency_ms=latency_ms, message=err)
