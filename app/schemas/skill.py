"""Schemas Skills Center (0.38.0).

I/O API pour /settings/skills + /settings/skills/active (loader
assistant). Validation stricte côté serveur (``services.skills``) ;
les schemas ici ne font qu'imposer la shape du JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SkillStatus = Literal["draft", "validated", "active", "archived"]


class SkillCreate(BaseModel):
    """Création : le body est le Markdown COMPLET (frontmatter + corps).

    Le serveur extrait et persiste les champs structurés via le
    validateur. L'ingestion directe de JSON structuré est explicitement
    REFUSÉE : la source de vérité est le Markdown.
    """

    body_md: str = Field(..., min_length=1, max_length=20000)


class SkillUpdate(BaseModel):
    """Mise à jour : seule la source Markdown est éditable. L'édition
    repasse le skill en ``draft`` (une version activée est immutable —
    pour une nouvelle version, bump la clé ``version:`` dans le
    frontmatter, le serveur détectera un nouvel enregistrement).
    """

    body_md: str = Field(..., min_length=1, max_length=20000)


class SkillOut(BaseModel):
    """Vue publique d'un skill persisté."""

    id: str
    slug: str
    name: str
    version: str
    description: str
    triggers: list[str]
    tools_allowed: list[str]
    scope: str | None = None
    render: list[str] | None = None
    body_md: str
    status: SkillStatus
    created_by: str | None = None
    validated_by: str | None = None
    validated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SkillSummary(BaseModel):
    """Vue allégée exposée au loader assistant.

    Contient uniquement les champs nécessaires pour que l'intent LLM
    puisse décider d'un skill (name, description, triggers). La section
    Procédure n'est injectée que si le LLM a sélectionné le skill —
    elle vit dans ``body_md`` côté serveur et n'est pas renvoyée ici.
    """

    slug: str
    version: str
    name: str
    description: str
    triggers: list[str]
    tools_allowed: list[str]


class SkillValidateResult(BaseModel):
    """Sortie de ``POST /settings/skills/{id}/validate``.

    ``errors`` est une liste **nominative** : chaque entrée nomme le
    champ ou la règle fautive (ex. ``tools_allowed[2] 'rm -rf' hors
    liste blanche``). Jamais un message générique.
    """

    ok: bool
    errors: list[str] = Field(default_factory=list)


class SkillUsedTag(BaseModel):
    """Trace du skill utilisé par un run d'assistant (dans la réponse)."""

    slug: str
    version: str
