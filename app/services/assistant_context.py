"""Construit le `context_facts` injecté dans le prompt LLM (0.22.0+).

Règle d'or : **on n'invente aucun chiffre**. Chaque ligne de contexte
est dérivée d'une requête réelle en DB sur le `project_id` et les
filtres actifs. Le LLM reçoit un bloc texte compact et verrouillé —
le prompt système lui interdit déjà d'ajouter des chiffres hors
contexte, et ce helper garantit que le contexte reflète la DB.

Deux familles de projets côté BC4 :
- **Projets seedés / avec `measurement_points`** : agrégats
  opérateur × bande sur les mesures (débits, lat/lon, etc.).
- **Projets ingérés (NMF)** : `param_occurrence` (RRC décodé) est la
  source — les mesures lat/lon synthétiques sont absentes mais le
  dictionnaire est riche (top messages, top paramètres).

Les deux sections sont émises séparément (préfixe `[MP]` / `[RRC]`)
pour que le LLM comprenne la provenance de chaque chiffre.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import MeasurementPoint, ParamOccurrence, Project
from app.schemas.assistant import AssistantFilters


def _apply_mp_filters(q, filters: AssistantFilters):
    if filters.op:
        q = q.filter(MeasurementPoint.operator.in_(filters.op))
    if filters.tech:
        q = q.filter(MeasurementPoint.tech.in_(filters.tech))
    if filters.svc:
        q = q.filter(MeasurementPoint.service.in_(filters.svc))
    if filters.band:
        q = q.filter(MeasurementPoint.band.in_(filters.band))
    if filters.dep:
        q = q.filter(MeasurementPoint.dep.in_(filters.dep))
    return q


def _apply_po_filters(q, filters: AssistantFilters):
    if filters.op:
        q = q.filter(ParamOccurrence.operator.in_(filters.op))
    if filters.band:
        q = q.filter(ParamOccurrence.band.in_(filters.band))
    return q


def _fmt_list(xs: list[str], max_items: int = 8) -> str:
    """Rend une liste comme `a, b, c` (… si tronquée). Vide → `aucun`."""
    if not xs:
        return "aucun"
    if len(xs) <= max_items:
        return ", ".join(xs)
    return ", ".join(xs[:max_items]) + f" (+ {len(xs) - max_items} autres)"


def _mp_section(db: Session, project_id: str, filters: AssistantFilters) -> tuple[int, list[str]]:
    """Retourne `(sample_count, lignes_contexte)` pour la section `[MP]`.

    Si `sample_count == 0`, les lignes `op/band` sont omises (pas de
    contexte à inventer). Toujours une ligne `[MP] n=…` pour signaler
    la présence/absence.
    """
    base = db.query(MeasurementPoint).filter(MeasurementPoint.project_id == project_id)
    scoped = _apply_mp_filters(base, filters)
    n = scoped.count()
    out: list[str] = [f"[MP] n={n} points de mesure correspondent aux filtres."]
    if n == 0:
        return n, out

    # Top opérateurs par volume (dans le périmètre filtré).
    rows = (
        _apply_mp_filters(
            db.query(MeasurementPoint.operator, func.count().label("c")).filter(
                MeasurementPoint.project_id == project_id
            ),
            filters,
        )
        .group_by(MeasurementPoint.operator)
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    if rows:
        out.append(
            "[MP] Opérateurs présents (ordre décroissant): "
            + ", ".join(f"{op}={c}" for op, c in rows if op)
        )

    # Top bandes par volume.
    rows = (
        _apply_mp_filters(
            db.query(MeasurementPoint.band, func.count().label("c")).filter(
                MeasurementPoint.project_id == project_id
            ),
            filters,
        )
        .group_by(MeasurementPoint.band)
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    if rows:
        out.append(
            "[MP] Bandes présentes: " + ", ".join(f"{b}={c}" for b, c in rows if b)
        )
    return n, out


def _rrc_section(db: Session, project_id: str, filters: AssistantFilters) -> tuple[int, list[str]]:
    """Retourne `(total_occurrences, lignes)` pour la section `[RRC]`.

    Toujours une ligne `[RRC] n=…`. Si `n>0` : top 5 messages, top 10
    paramètres, répartition opérateur/bande.
    """
    base = db.query(ParamOccurrence).filter(ParamOccurrence.project_id == project_id)
    scoped = _apply_po_filters(base, filters)
    n = scoped.count()
    out: list[str] = [f"[RRC] n={n} occurrences RRC décodées (dict param_occurrence)."]
    if n == 0:
        return n, out

    # Top messages
    rows = (
        _apply_po_filters(
            db.query(ParamOccurrence.message, func.count().label("c")).filter(
                ParamOccurrence.project_id == project_id
            ),
            filters,
        )
        .group_by(ParamOccurrence.message)
        .order_by(func.count().desc())
        .limit(5)
        .all()
    )
    if rows:
        out.append(
            "[RRC] Top 5 messages (nom=occurrences): "
            + ", ".join(f"{m}={c}" for m, c in rows)
        )

    # Top paramètres (path)
    rows = (
        _apply_po_filters(
            db.query(ParamOccurrence.path, func.count().label("c")).filter(
                ParamOccurrence.project_id == project_id
            ),
            filters,
        )
        .group_by(ParamOccurrence.path)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    if rows:
        out.append(
            "[RRC] Top 10 paramètres (path=occurrences): "
            + "; ".join(f"{p}={c}" for p, c in rows)
        )

    # Opérateurs présents dans le dict
    rows = (
        _apply_po_filters(
            db.query(ParamOccurrence.operator, func.count().label("c")).filter(
                ParamOccurrence.project_id == project_id
            ),
            filters,
        )
        .group_by(ParamOccurrence.operator)
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    present = [f"{op}={c}" for op, c in rows if op]
    if present:
        out.append("[RRC] Opérateurs présents: " + ", ".join(present))

    # Bandes présentes
    rows = (
        _apply_po_filters(
            db.query(ParamOccurrence.band, func.count().label("c")).filter(
                ParamOccurrence.project_id == project_id
            ),
            filters,
        )
        .group_by(ParamOccurrence.band)
        .order_by(func.count().desc())
        .limit(8)
        .all()
    )
    present = [f"{b}={c}" for b, c in rows if b]
    if present:
        out.append("[RRC] Bandes présentes: " + ", ".join(present))
    return n, out


def build_context_facts(
    db: Session, project: Project, filters: AssistantFilters
) -> tuple[str, dict[str, Any]]:
    """Construit le bloc `context_facts` + métadonnées pour la réponse.

    Retourne `(context_facts, meta)` où `meta` sert à :
    - alimenter `sample_count` historique dans la route (OBSERVED block),
    - décider si on a besoin d'un claim UNAVAILABLE « projet vide ».

    `meta` keys: `mp_count`, `rrc_count`.
    """
    lines: list[str] = []
    lines.append(f"Projet: {project.name} (id={project.id}).")
    lines.append(f"Période: {project.period_start} → {project.period_end}.")

    # Métadonnées projet (toujours disponibles, viennent de l'ingestion
    # ou du seed). Jamais inventées — si vides, on dit `aucun`.
    ops = list(project.operators or [])
    techs = list(project.technologies or [])
    bands = list(project.bands or [])
    lines.append(f"Projet.operators (métadonnées): {_fmt_list(ops)}.")
    lines.append(f"Projet.technologies: {_fmt_list(techs)}.")
    lines.append(f"Projet.bands: {_fmt_list(bands)}.")

    lines.append(
        f"Filtres appliqués: op={filters.op or []}, tech={filters.tech or []}, "
        f"svc={filters.svc or []}, band={filters.band or []}, dep={filters.dep or []}."
    )

    mp_count, mp_lines = _mp_section(db, project.id, filters)
    lines.extend(mp_lines)

    rrc_count, rrc_lines = _rrc_section(db, project.id, filters)
    lines.extend(rrc_lines)

    # Garde-fou pour le LLM : s'il n'y a NI mesure NI dict, on le dit
    # explicitement — évite une réponse qui ferait croire à des données.
    if mp_count == 0 and rrc_count == 0:
        lines.append(
            "ATTENTION: aucune mesure ni occurrence RRC n'est disponible dans ce périmètre. "
            "La seule chose factuelle est le nom et la période du projet. "
            "Toute réponse chiffrée serait une invention — refuse-la."
        )

    return "\n".join(lines), {"mp_count": mp_count, "rrc_count": rrc_count}
