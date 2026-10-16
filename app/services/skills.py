"""Skills Center — parse + validate + loader (0.38.0).

Un skill est un **fichier Markdown** avec frontmatter YAML. Il ne
contient JAMAIS de code exécutable. Le validateur ici est strict,
déterministe, et renvoie une liste d'erreurs **nominative** — jamais
un message générique.

Discipline absolue (rappelée au point d'intégration pipeline) :
- Le skill GUIDE, il n'exécute rien.
- Les invariants du pipeline (feasibility, scope projet, états typés,
  compose déterministe, vérificateur anti-invention) priment sur
  TOUT texte issu d'un skill. Un skill qui tente d'« ignorer le
  vérificateur », de « renvoyer les lignes brutes » ou de « changer
  de projet » est ignoré sur ces points, warning loggé.
- ``tools_allowed`` est **intersecté** avec la liste blanche du moteur ;
  un skill ne peut pas élargir la surface d'attaque.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.models import Skill


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Liste blanche d'outils connus par le pipeline (0.38.0 — assistant V3).
# Un ``tools_allowed`` qui référence un outil hors de cette liste est
# REFUSÉ au validate avec un message nominatif.
# ---------------------------------------------------------------------------

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_project_context",
        "list_operators",
        "list_bands",
        "top_rrc_messages",
        "rrc_param_distribution",
        "compare_operators",
        "compare_distributions",
        "map_metric",
    }
)


# ---------------------------------------------------------------------------
# Limites et grammaire
# ---------------------------------------------------------------------------

MAX_BODY_LEN = 20_000  # chars — garde contre les skills « roman »
REQUIRED_FM_FIELDS = ("name", "version", "description", "triggers", "tools_allowed")
REQUIRED_SECTIONS = ("Quand", "Procédure", "Rendu")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([\-+][0-9A-Za-z\.\-]+)?$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9\-]{1,63}$")
# Blocs de code exécutable REFUSÉS (quelle que soit la casse).
_FORBIDDEN_CODE_LANGS = ("python", "py", "sql", "js", "javascript", "ts", "bash", "sh", "shell")
_CODE_FENCE_RE = re.compile(r"```\s*([A-Za-z0-9+_-]+)\s*\n", re.MULTILINE)
# Marqueurs de bypass (« ignore le vérificateur »…) — pas rejet au
# validate (c'est du prose libre), mais ignorés AU RUNTIME avec un
# warning explicite. On les détecte ici pour éclairer l'intégration.
_BYPASS_HINTS = (
    "ignore le vérificateur",
    "ignore le verificateur",
    "ignore the verifier",
    "lignes brutes",
    "raw rows",
    "change de projet",
    "autre project",
    "autre projet",
)


# ---------------------------------------------------------------------------
# Parse frontmatter + body
# ---------------------------------------------------------------------------


def _split_frontmatter(body_md: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Sépare ``body_md`` en ``(frontmatter_dict, markdown_body, errors)``.

    Grammaire attendue :
        ---
        key: value
        ...
        ---
        # Markdown
    Un seul bloc de frontmatter, au tout début du document, délimité
    par ``---`` sur sa propre ligne.
    """
    errors: list[str] = []
    txt = (body_md or "").lstrip()
    if not txt.startswith("---"):
        errors.append("frontmatter: le fichier doit commencer par '---'")
        return None, body_md, errors

    # Cherche le second '---' sur sa propre ligne.
    lines = txt.splitlines(keepends=True)
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        errors.append("frontmatter: délimiteur de fin '---' introuvable")
        return None, body_md, errors

    fm_text = "".join(lines[1:end_idx])
    md_text = "".join(lines[end_idx + 1 :]).lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        errors.append(f"frontmatter: YAML invalide ({exc!s})")
        return None, md_text, errors

    if not isinstance(fm, dict):
        errors.append("frontmatter: la racine doit être un mapping (clé: valeur)")
        return None, md_text, errors

    return fm, md_text, errors


# ---------------------------------------------------------------------------
# Validate (returns errors — never raises on bad input)
# ---------------------------------------------------------------------------


def validate_skill(body_md: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Valide le body Markdown d'un skill.

    Retourne ``(frontmatter_dict | None, markdown_body, errors)``.
    ``errors`` est **toujours** une liste (vide si tout va bien).
    """
    errors: list[str] = []
    body_md = body_md or ""

    if len(body_md) > MAX_BODY_LEN:
        errors.append(
            f"body_md: taille {len(body_md)} > max {MAX_BODY_LEN} caractères"
        )
        return None, body_md, errors

    fm, md, fm_errors = _split_frontmatter(body_md)
    errors.extend(fm_errors)
    if fm is None:
        return None, md, errors

    # Champs requis
    for field in REQUIRED_FM_FIELDS:
        if field not in fm:
            errors.append(f"frontmatter: champ requis manquant '{field}'")

    # name
    name = fm.get("name")
    if "name" in fm and not isinstance(name, str):
        errors.append(f"frontmatter.name: type attendu str, reçu {type(name).__name__}")
    elif isinstance(name, str) and not name.strip():
        errors.append("frontmatter.name: chaîne vide")

    # version — SemVer
    version = fm.get("version")
    if version is None and "version" in fm:
        errors.append("frontmatter.version: valeur null")
    elif version is not None and not isinstance(version, str):
        errors.append(f"frontmatter.version: type attendu str, reçu {type(version).__name__}")
    elif isinstance(version, str) and not _SEMVER_RE.match(version):
        errors.append(
            f"frontmatter.version: {version!r} n'est pas un SemVer "
            f"(MAJOR.MINOR.PATCH, ex. '1.0.0')"
        )

    # description
    desc = fm.get("description")
    if "description" in fm and not isinstance(desc, str):
        errors.append(
            f"frontmatter.description: type attendu str, reçu {type(desc).__name__}"
        )
    elif isinstance(desc, str) and not desc.strip():
        errors.append("frontmatter.description: chaîne vide")

    # triggers
    triggers = fm.get("triggers")
    if "triggers" in fm:
        if not isinstance(triggers, list):
            errors.append(
                f"frontmatter.triggers: type attendu list[str], reçu {type(triggers).__name__}"
            )
        else:
            if not triggers:
                errors.append("frontmatter.triggers: liste vide (au moins 1 trigger requis)")
            for i, t in enumerate(triggers):
                if not isinstance(t, str) or not t.strip():
                    errors.append(f"frontmatter.triggers[{i}]: chaîne non vide attendue")

    # tools_allowed : liste de str ⊆ ALLOWED_TOOLS
    tools = fm.get("tools_allowed")
    if "tools_allowed" in fm:
        if not isinstance(tools, list):
            errors.append(
                f"frontmatter.tools_allowed: type attendu list[str], reçu {type(tools).__name__}"
            )
        else:
            if not tools:
                errors.append(
                    "frontmatter.tools_allowed: liste vide (un skill doit déclarer les outils qu'il peut appeler)"
                )
            for i, t in enumerate(tools):
                if not isinstance(t, str):
                    errors.append(
                        f"frontmatter.tools_allowed[{i}]: chaîne attendue, reçu {type(t).__name__}"
                    )
                    continue
                if t not in ALLOWED_TOOLS:
                    errors.append(
                        f"frontmatter.tools_allowed[{i}] {t!r} hors liste blanche moteur "
                        f"(outils admis: {sorted(ALLOWED_TOOLS)})"
                    )

    # slug (optionnel au frontmatter — si absent, dérivé de name).
    slug = fm.get("slug")
    if slug is not None:
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            errors.append(
                f"frontmatter.slug: {slug!r} invalide (ascii lowercase, 2-64 chars, "
                "commence par une lettre, tirets autorisés)"
            )

    # scope (optionnel — ex. 'project', 'global')
    scope = fm.get("scope")
    if scope is not None and not isinstance(scope, str):
        errors.append(f"frontmatter.scope: type attendu str, reçu {type(scope).__name__}")

    # render (optionnel — list[str])
    render = fm.get("render")
    if render is not None:
        if not isinstance(render, list) or not all(isinstance(x, str) for x in render):
            errors.append("frontmatter.render: type attendu list[str]")

    # default_metric (optionnel — str catalogue). Si fourni, la pipeline
    # l'utilisera UNIQUEMENT quand le LLM d'intention a laissé
    # metric_key=null (le skill guide, il n'écrase pas une métrique
    # déjà bindée par le LLM à partir de la question).
    default_metric = fm.get("default_metric")
    if default_metric is not None and not isinstance(default_metric, str):
        errors.append(
            f"frontmatter.default_metric: type attendu str, reçu {type(default_metric).__name__}"
        )

    # default_operation (optionnel — opération assistant). Même règle :
    # n'écrase JAMAIS l'opération extraite par le LLM, utilisé seulement
    # si l'extraction retombe sur describe/list sans metric.
    default_operation = fm.get("default_operation")
    allowed_ops = ("list", "distribution", "compare", "map", "trend", "describe")
    if default_operation is not None:
        if not isinstance(default_operation, str) or default_operation not in allowed_ops:
            errors.append(
                f"frontmatter.default_operation: attendu une des valeurs "
                f"{allowed_ops}, reçu {default_operation!r}"
            )

    # Blocs de code exécutable interdits (quelle que soit la langue
    # listée en ligne d'ouverture ``` <lang>).
    for m in _CODE_FENCE_RE.finditer(md):
        lang = (m.group(1) or "").lower()
        if lang in _FORBIDDEN_CODE_LANGS:
            errors.append(
                f"body: bloc de code exécutable interdit '```{lang}' "
                "(un skill est déclaratif, jamais exécutable)"
            )

    # Sections requises
    for section in REQUIRED_SECTIONS:
        # Match ## Section OU ### Section (indifférent du niveau)
        pat = re.compile(rf"^\s{{0,3}}#{{1,6}}\s+{re.escape(section)}\b", re.MULTILINE)
        if not pat.search(md):
            errors.append(f"body: section requise manquante '## {section}'")

    return fm, md, errors


# ---------------------------------------------------------------------------
# Normalisation : frontmatter → row ORM
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Fallback slug : minuscule, tirets, 2..64. On ne corrige PAS
    silencieusement — si ``_SLUG_RE`` ne match pas après transformation,
    l'appelant émet une erreur plutôt que d'inventer un slug."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:64]


def frontmatter_to_fields(fm: dict[str, Any], body_md: str) -> dict[str, Any]:
    """Convertit un frontmatter validé en kwargs ``Skill`` ORM.

    Les champs optionnels `default_metric` / `default_operation` ne sont
    PAS persistés en colonne dédiée : ils vivent dans le body_md (le
    pipeline les relira via :func:`extract_defaults`). Garde le modèle
    DB stable (migration 0015 inchangée).
    """
    slug = fm.get("slug") or _slugify(fm["name"])
    return {
        "slug": slug,
        "name": fm["name"],
        "version": fm["version"],
        "description": fm["description"],
        "triggers": list(fm.get("triggers") or []),
        "tools_allowed": list(fm.get("tools_allowed") or []),
        "scope": fm.get("scope"),
        "render": list(fm.get("render") or []) if fm.get("render") is not None else None,
        "body_md": body_md,
    }


def extract_defaults(body_md: str) -> tuple[str | None, str | None]:
    """Relit `default_metric` / `default_operation` depuis le body_md
    du skill. Retourne ``(default_metric, default_operation)``.

    Si l'un n'est pas présent (ou le frontmatter est invalide), retourne
    ``(None, None)``. Jamais une exception — le pipeline ne doit pas
    casser à cause d'un skill malformé.
    """
    try:
        fm, _, errs = _split_frontmatter(body_md or "")
        if fm is None or errs:
            return None, None
        dm = fm.get("default_metric")
        do = fm.get("default_operation")
        return (dm if isinstance(dm, str) else None,
                do if isinstance(do, str) else None)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Loader — liste des skills ACTIFS pour l'assistant
# ---------------------------------------------------------------------------


def load_active_skills(db: Session) -> list[Skill]:
    """Retourne les skills ``status='active'`` triés par slug.

    Appelé par l'intent LLM pour exposer la carte des skills au modèle.
    """
    return (
        db.query(Skill)
        .filter(Skill.status == "active")
        .order_by(Skill.slug.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Procédure extraction — section « Procédure » comme texte
# ---------------------------------------------------------------------------


def extract_procedure(body_md: str) -> str | None:
    """Extrait le texte de la section ``## Procédure`` (jusqu'à la
    prochaine section ou fin de document). Utilisé pour injecter une
    guidance BORNÉE au planificateur quand un skill est sélectionné.

    Retourne ``None`` si la section est introuvable (le validateur
    l'aurait refusée en amont, mais défensif).
    """
    pat = re.compile(
        r"^\s{0,3}#{1,6}\s+Procédure\b.*?\n(?P<body>.*?)"
        r"(?=^\s{0,3}#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(body_md or "")
    if not m:
        return None
    return m.group("body").strip() or None


def body_has_bypass_hints(body_md: str) -> list[str]:
    """Détecte dans le body des marqueurs de bypass (ex. « ignore le
    vérificateur », « lignes brutes », « change de projet »).

    Retourne la liste des hints TROUVÉS (vide si aucun). Ne fait PAS
    de rejet au validate — c'est du prose libre. Le pipeline l'utilise
    pour émettre un warning explicite à chaque exécution.
    """
    low = (body_md or "").lower()
    return [h for h in _BYPASS_HINTS if h in low]


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------


def new_skill_id() -> str:
    return uuid.uuid4().hex[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
