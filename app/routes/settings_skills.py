"""Routes Skills Center — admin + loader (0.38.0).

Toutes les routes CRUD + validate/activate/archive sont ``admin``.
Le ``GET /settings/skills/active`` est accessible aux ``viewer`` : c'est
le loader que l'assistant appelle pour montrer la carte des skills à
l'intent LLM.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_actor, require_role
from app.schemas.settings import Actor
from app.models import AppUser, Skill
from app.schemas.skill import (
    SkillCreate,
    SkillOut,
    SkillSummary,
    SkillUpdate,
    SkillValidateResult,
)
from app.services.skills import (
    frontmatter_to_fields,
    new_skill_id,
    utcnow,
    validate_skill,
)


router = APIRouter(prefix="/settings/skills", tags=["settings-skills"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skill_to_out(s: Skill) -> SkillOut:
    return SkillOut(
        id=s.id,
        slug=s.slug,
        name=s.name,
        version=s.version,
        description=s.description,
        triggers=list(s.triggers or []),
        tools_allowed=list(s.tools_allowed or []),
        scope=s.scope,
        render=list(s.render or []) if s.render is not None else None,
        body_md=s.body_md,
        status=s.status,  # type: ignore[arg-type]
        created_by=s.created_by,
        validated_by=s.validated_by,
        validated_at=s.validated_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _get_or_404(db: Session, skill_id: str) -> Skill:
    s = db.query(Skill).filter(Skill.id == skill_id).one_or_none()
    if s is None:
        raise HTTPException(
            404, {"code": "SKILL_NOT_FOUND", "message": f"Skill {skill_id!r} introuvable"}
        )
    return s


def _actor_user_id(db: Session, actor: Actor) -> str | None:
    """Résout l'`AppUser.id` à partir de l'email `actor.login`. Retourne
    ``None`` si le compte n'existe pas (compte seed hors `app_user`
    par exemple) — le FK ``created_by`` est `ON DELETE SET NULL`, on
    préserve donc la ligne skill avec un ``created_by`` nul plutôt que
    d'échouer la création.
    """
    row = db.query(AppUser).filter(AppUser.email == actor.login).one_or_none()
    return row.id if row else None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[SkillOut])
def list_skills(
    status: str | None = None,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> list[SkillOut]:
    """Liste tous les skills (ou filtrés par ``status``). Admin."""
    require_role(actor, "admin")
    q = db.query(Skill)
    if status:
        q = q.filter(Skill.status == status)
    return [_skill_to_out(s) for s in q.order_by(Skill.slug.asc(), Skill.version.asc()).all()]


@router.get("/active", response_model=list[SkillSummary])
def list_active_skills(
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> list[SkillSummary]:
    """Loader assistant : skills ``active`` + shape allégée.

    Accessible aux ``viewer`` — c'est la vue publique qui alimente la
    décision du LLM d'extraction d'intention. La section Procédure
    reste côté serveur.
    """
    require_role(actor, "admin", "editor", "viewer")
    rows = (
        db.query(Skill)
        .filter(Skill.status == "active")
        .order_by(Skill.slug.asc())
        .all()
    )
    return [
        SkillSummary(
            slug=s.slug,
            version=s.version,
            name=s.name,
            description=s.description,
            triggers=list(s.triggers or []),
            tools_allowed=list(s.tools_allowed or []),
        )
        for s in rows
    ]


@router.get("/{skill_id}", response_model=SkillOut)
def get_skill(
    skill_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillOut:
    require_role(actor, "admin")
    return _skill_to_out(_get_or_404(db, skill_id))


@router.post("", response_model=SkillOut, status_code=201)
def create_skill(
    payload: SkillCreate,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillOut:
    """Crée un skill en status ``draft``.

    Le validateur n'est PAS exécuté ici — on persiste le body tel quel
    pour permettre l'édition de brouillons incomplets. L'appel à
    ``POST /settings/skills/{id}/validate`` fait la vérification et met
    le status à ``validated`` si tout passe.
    """
    require_role(actor, "admin")
    # Extraction best-effort du frontmatter pour renseigner les champs
    # structurés (nécessaires à `slug` / `version` indispensables en DB
    # vu la contrainte uq_skill_slug_version). Si le frontmatter est
    # invalide, on refuse DÈS LA CRÉATION — le validateur du validate
    # est pour les règles métier/sections ; les champs d'identification
    # DB ne tolèrent pas l'absence.
    fm, md, errs = validate_skill(payload.body_md)
    missing_core = [e for e in errs if any(
        tok in e for tok in (
            "frontmatter: le fichier",
            "frontmatter: délimiteur",
            "frontmatter: YAML invalide",
            "frontmatter.name",
            "frontmatter.version",
            "frontmatter.description",
        )
    )]
    if fm is None or missing_core:
        # Impossible de persister sans slug/version/name.
        raise HTTPException(
            400,
            {
                "code": "SKILL_FRONTMATTER_INVALID",
                "message": "Frontmatter incomplet : impossible de créer sans slug/version/name/description",
                "errors": missing_core or errs,
            },
        )

    fields = frontmatter_to_fields(fm, payload.body_md)

    # Unicité (slug, version)
    dup = (
        db.query(Skill)
        .filter(Skill.slug == fields["slug"], Skill.version == fields["version"])
        .one_or_none()
    )
    if dup is not None:
        raise HTTPException(
            409,
            {
                "code": "SKILL_DUPLICATE",
                "message": f"Un skill {fields['slug']!r} version {fields['version']!r} existe déjà",
            },
        )

    row = Skill(
        id=new_skill_id(),
        status="draft",
        created_by=_actor_user_id(db, actor),
        created_at=utcnow(),
        updated_at=utcnow(),
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _skill_to_out(row)


@router.put("/{skill_id}", response_model=SkillOut)
def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillOut:
    """Édite un skill. Un skill actif n'est PAS éditable — bump la
    version dans le frontmatter pour créer un nouvel enregistrement.
    """
    require_role(actor, "admin")
    row = _get_or_404(db, skill_id)
    if row.status == "active":
        raise HTTPException(
            409,
            {
                "code": "SKILL_IMMUTABLE_ACTIVE",
                "message": "Un skill actif est immutable. Bump 'version:' pour une nouvelle version, "
                "ou archive avant d'éditer.",
            },
        )

    fm, md, errs = validate_skill(payload.body_md)
    missing_core = [e for e in errs if any(
        tok in e for tok in (
            "frontmatter: le fichier",
            "frontmatter: délimiteur",
            "frontmatter: YAML invalide",
            "frontmatter.name",
            "frontmatter.version",
            "frontmatter.description",
        )
    )]
    if fm is None or missing_core:
        raise HTTPException(
            400,
            {
                "code": "SKILL_FRONTMATTER_INVALID",
                "message": "Frontmatter incomplet",
                "errors": missing_core or errs,
            },
        )

    fields = frontmatter_to_fields(fm, payload.body_md)

    # L'identité (slug, version) doit rester celle du row (sinon on
    # oblige à créer un nouvel enregistrement — pas de bascule
    # silencieuse qui écraserait l'historique).
    if fields["slug"] != row.slug or fields["version"] != row.version:
        raise HTTPException(
            409,
            {
                "code": "SKILL_IDENTITY_CHANGED",
                "message": (
                    f"L'identité (slug, version) ne peut pas changer sur PUT. "
                    f"Attendu ({row.slug!r}, {row.version!r}), "
                    f"reçu ({fields['slug']!r}, {fields['version']!r}). "
                    "POST un nouveau skill pour une autre version."
                ),
            },
        )

    for k, v in fields.items():
        setattr(row, k, v)
    # Édition rebascule en 'draft' — la validation précédente ne vaut
    # plus pour le nouveau body.
    row.status = "draft"
    row.validated_by = None
    row.validated_at = None
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _skill_to_out(row)


@router.delete("/{skill_id}", status_code=204, response_class=Response)
def delete_skill(
    skill_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> Response:
    """Supprime un skill. Un skill actif ne peut pas être supprimé —
    archiver d'abord (``POST /archive``) puis supprimer.
    """
    require_role(actor, "admin")
    row = _get_or_404(db, skill_id)
    if row.status == "active":
        raise HTTPException(
            409,
            {
                "code": "SKILL_ACTIVE_NOT_DELETABLE",
                "message": "Un skill actif n'est pas supprimable. Archive d'abord.",
            },
        )
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Lifecycle : validate / activate / archive
# ---------------------------------------------------------------------------


@router.post("/{skill_id}/validate", response_model=SkillValidateResult)
def validate_skill_route(
    skill_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillValidateResult:
    """Valide un skill. Si OK, status → ``validated``. Sinon la liste
    des erreurs est retournée, status INCHANGÉ. Aucun chargement par
    l'assistant tant que ``status != 'active'``.
    """
    require_role(actor, "admin")
    row = _get_or_404(db, skill_id)
    _, _, errs = validate_skill(row.body_md)
    if errs:
        return SkillValidateResult(ok=False, errors=errs)
    row.status = "validated"
    row.validated_by = _actor_user_id(db, actor)
    row.validated_at = utcnow()
    row.updated_at = utcnow()
    db.commit()
    return SkillValidateResult(ok=True, errors=[])


@router.post("/{skill_id}/activate", response_model=SkillOut)
def activate_skill(
    skill_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillOut:
    """Active un skill ``validated``.

    Un seul actif par slug : les autres versions actives du même slug
    passent en ``archived`` dans la même transaction (historique
    conservé, jamais écrasé).
    """
    require_role(actor, "admin")
    row = _get_or_404(db, skill_id)
    if row.status != "validated":
        raise HTTPException(
            409,
            {
                "code": "SKILL_NOT_VALIDATED",
                "message": f"Skill status={row.status!r} — valide-le d'abord via POST /validate",
            },
        )
    # Re-valide pour détecter une dérive (ex. tools whitelist élargie
    # depuis la validation précédente ne devrait pas pouvoir inclure
    # un outil qui n'existe plus — défensif).
    _, _, errs = validate_skill(row.body_md)
    if errs:
        raise HTTPException(
            409,
            {
                "code": "SKILL_REVALIDATION_FAILED",
                "message": "Le body a dérivé depuis la validation précédente.",
                "errors": errs,
            },
        )

    # Archive les autres actifs du même slug.
    db.query(Skill).filter(
        Skill.slug == row.slug,
        Skill.status == "active",
        Skill.id != row.id,
    ).update({"status": "archived", "updated_at": utcnow()}, synchronize_session=False)

    row.status = "active"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _skill_to_out(row)


@router.post("/{skill_id}/archive", response_model=SkillOut)
def archive_skill(
    skill_id: str,
    actor: Actor = Depends(get_actor),
    db: Session = Depends(get_db),
) -> SkillOut:
    """Archive un skill. Il devient non sélectionnable par l'assistant."""
    require_role(actor, "admin")
    row = _get_or_404(db, skill_id)
    row.status = "archived"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _skill_to_out(row)
