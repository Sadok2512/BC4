"""Faisabilité V3 : la métrique de l'intent est-elle disponible ? (0.28.0)

Avant toute exécution, vérifier que la métrique canonique de l'Intent
peut effectivement être calculée sur le projet actif. Si NON :
`OUTCOME = UNAVAILABLE` + raison claire + stop propre. **Jamais de
substitution automatique de métrique**.

Vérifications :
- `source_dataset` vide pour ce projet → `UNAVAILABLE`.
- Si `available_check` défini : exécuter la vérif correspondante
  (ex. colonne `dl` ou `thrpt_ul` populate ?). NULL partout → UNAVAILABLE.
- Résolution d'ambiguïté `path_match` : si > 1 path distinct matche
  dans la DB → remonte en liste pour clarification UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assistant.metrics import CATALOG, CanonicalMetric


@dataclass
class Feasibility:
    ok: bool
    reason: str = ""
    # Si ambigu au niveau DB (plusieurs paths), on remonte les candidats.
    ambiguous_paths: list[str] = field(default_factory=list)
    sample_count: int = 0  # cardinalité du dataset filtré (indicative)


# Nombre maximum de paths à inspecter en cas d'ambiguïté.
_AMBIG_LIMIT = 20


def _dataset_count(db: Session, dataset: str, project_id: str) -> int:
    table = {"rrc_dict": "param_occurrence", "measurements": "measurement_points"}[dataset]
    return int(
        db.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar_one()
    )


def _column_populated(db: Session, project_id: str, column: str) -> int:
    """Compte combien de lignes de measurement_points ont `column IS NOT NULL`."""
    return int(
        db.execute(
            text(f"SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid AND {column} IS NOT NULL"),
            {"pid": project_id},
        ).scalar_one()
    )


def _distinct_paths(
    db: Session, project_id: str, patterns: tuple[str, ...], excludes: tuple[str, ...] = ()
) -> list[str]:
    if not patterns:
        return []
    conditions = " OR ".join(f"path LIKE :p{i}" for i in range(len(patterns)))
    params: dict[str, Any] = {"pid": project_id}
    for i, pat in enumerate(patterns):
        params[f"p{i}"] = pat
    exclude_sql = ""
    for i, exc in enumerate(excludes):
        exclude_sql += f" AND path NOT LIKE :ex{i}"
        params[f"ex{i}"] = exc
    rows = db.execute(
        text(
            f"SELECT DISTINCT path FROM param_occurrence "
            f"WHERE project_id = :pid AND ({conditions}){exclude_sql} LIMIT {_AMBIG_LIMIT + 1}"
        ),
        params,
    ).all()
    return [r[0] for r in rows]


def check(db: Session, project_id: str, metric_key: str | None) -> Feasibility:
    """Vérifie que `metric_key` est faisable pour `project_id`.

    `metric_key=None` : l'intent n'a pas de métrique (ex. opération
    `conversation` ou `list` sans mesure explicite). Faisabilité OK —
    l'exécution utilisera `count` par défaut.
    """
    if metric_key is None:
        return Feasibility(ok=True, reason="pas de métrique explicite — count par défaut")

    m = CATALOG.get(metric_key)
    if m is None:
        return Feasibility(
            ok=False,
            reason=f"Métrique inconnue dans le catalogue : {metric_key!r}. "
            "Pas de substitution automatique autorisée.",
        )

    # 1) Dataset vide pour ce projet ?
    ds_count = _dataset_count(db, m.source_dataset, project_id)
    if ds_count == 0:
        return Feasibility(
            ok=False,
            reason=f"Dataset {m.source_dataset!r} vide pour ce projet (n=0). "
            f"Métrique {m.display!r} non calculable.",
            sample_count=0,
        )

    # 2) available_check spécifique (colonne vide ? message présent ?)
    ac = (m.available_check or "").strip()
    # 2a) colonnes measurement_points
    _MP_COLS = {
        "dl_populated": "dl",
        "thrpt_ul_populated": "thrpt_ul",
        "sinr_populated": "sinr",
        "cqi_populated": "cqi",
        "latency_populated": "latency",
        "rsrp_mp_populated": "rsrp",
        "rsrq_mp_populated": "rsrq",
    }
    if ac in _MP_COLS:
        col = _MP_COLS[ac]
        n = _column_populated(db, project_id, col)
        if n == 0:
            return Feasibility(
                ok=False,
                reason=(
                    f"Métrique {m.display!r} INDISPONIBLE : colonne "
                    f"`measurement_points.{col}` NULL partout (Phase 1 mapping "
                    f"décodeur non livrée — voir CHANGELOG 0.24.0). "
                    f"Aucune substitution autorisée."
                ),
                sample_count=ds_count,
            )
    # 2b) message RRC présent dans param_occurrence
    elif ac.startswith("message_present:"):
        needle = ac.split(":", 1)[1]
        n = int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM param_occurrence "
                    "WHERE project_id = :pid AND message = :m"
                ),
                {"pid": project_id, "m": needle},
            ).scalar_one()
        )
        if n == 0:
            return Feasibility(
                ok=False,
                reason=(
                    f"Métrique {m.display!r} INDISPONIBLE : aucun message "
                    f"RRC {needle!r} dans ce projet (n=0). "
                    f"Aucune substitution autorisée."
                ),
                sample_count=ds_count,
            )
    # 2c) path pattern présent dans param_occurrence
    elif ac.startswith("path_present:"):
        needle = ac.split(":", 1)[1]
        n = int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM param_occurrence "
                    "WHERE project_id = :pid AND path ILIKE :p"
                ),
                {"pid": project_id, "p": f"%{needle}%"},
            ).scalar_one()
        )
        if n == 0:
            return Feasibility(
                ok=False,
                reason=(
                    f"Métrique {m.display!r} INDISPONIBLE : aucun path "
                    f"contenant {needle!r} dans ce projet (n=0). "
                    f"Aucune substitution autorisée."
                ),
                sample_count=ds_count,
            )

    # 3) Résolution path pour les métriques `rrc_dict` : si plusieurs
    #    paths distincts matchent, on peut être face à une ambiguïté
    #    (ex. `a3-Offset` pourrait exister dans plusieurs variantes).
    if m.source_dataset == "rrc_dict" and m.path_match:
        paths = _distinct_paths(db, project_id, m.path_match, m.exclude_path_patterns)
        if len(paths) == 0:
            return Feasibility(
                ok=False,
                reason=(
                    f"Métrique {m.display!r} INDISPONIBLE : aucun path "
                    f"RRC matchant les patterns {m.path_match} dans ce projet."
                ),
                sample_count=ds_count,
            )
        if len(paths) > _AMBIG_LIMIT:
            return Feasibility(
                ok=False,
                reason=(
                    f"Métrique {m.display!r} ambiguë : > {_AMBIG_LIMIT} paths "
                    f"distincts matchent. Précise le paramètre exact ou "
                    f"restreint via un filtre `message`."
                ),
                ambiguous_paths=paths[:_AMBIG_LIMIT],
                sample_count=ds_count,
            )

    return Feasibility(ok=True, sample_count=ds_count)
