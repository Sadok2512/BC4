"""0.47.0 — Helper partagé pour les ``group_by`` dimensionnels basés sur
``cell_ref`` (``dor``, ``dr``, ``plaque``, ``arcep_zone``).

Règles :

- La jointure se fait **toujours** sur ``mp.ecgi = cell_ref.eci`` avec
  ``mp.ecgi_source = 'sib1_strict_capture_earfcn'`` (le fallback
  cross-capture n'est jamais pris en compte — 0.44.0 règle G8).
- Les points sans ECGI strict ou dont la cellule ne porte pas la
  dimension demandée sont **comptés** sous le libellé ``"N/D"`` — jamais
  filtrés silencieusement.
- Si le projet n'a aucune cellule portant la dimension (``cell_ref.<col>``
  tout NULL pour les ECGI observés), on renvoie
  ``available=False`` + ``reason`` lisible — les routes transforment ça
  en bloc ``status='UNAVAILABLE'`` au lieu de retourner des faux groupes.

Même mécanique prête pour ``dr`` / ``plaque`` / ``arcep_zone`` : il
suffit d'ajouter la clé à ``CELL_REF_DIMS`` et le front peut la demander
quand elle devient disponible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# Colonne cell_ref pour chaque group_by dimensionnel. L'ordre est aussi
# celui utilisé pour l'ordre d'affichage dans group_by_options.
CELL_REF_DIMS: dict[str, str] = {
    "dor":         "dor",
    "dr":          "dr",
    "plaque":      "plaque",
    "arcep_zone":  "arcep_zone",
}


_LABEL_FR: dict[str, str] = {
    "dor":         "DOR",
    "dr":          "DR",
    "plaque":      "Plaque",
    "arcep_zone":  "Zone ARCEP",
}


@dataclass(frozen=True)
class CellRefDimStatus:
    """Statut d'un ``group_by`` dimensionnel pour un projet."""
    key: str
    available: bool
    reason: str | None
    n_with_value: int
    n_total_mp: int

    @property
    def pct(self) -> float:
        if self.n_total_mp == 0:
            return 0.0
        return round(100.0 * self.n_with_value / self.n_total_mp, 2)


# SQL — join mp → cell_ref via ECGI strict. On agrège le `n` par
# dimension demandée. Les points sans ECGI strict ou sans valeur
# cell_ref tombent dans `N/D`.
_SQL_DIM_COVERAGE = """
    WITH strict_mp AS (
        SELECT ecgi
        FROM measurement_points
        WHERE project_id = :pid
          AND ecgi IS NOT NULL
          AND ecgi_source = 'sib1_strict_capture_earfcn'
    ),
    cells AS (
        SELECT eci, {col} AS dim_val FROM cell_ref
        WHERE {col} IS NOT NULL AND eci IS NOT NULL
    )
    SELECT
        COUNT(*) FILTER (WHERE c.dim_val IS NOT NULL)         AS n_with_value,
        COUNT(*)                                              AS n_total_strict
    FROM strict_mp m
    LEFT JOIN cells c ON c.eci = m.ecgi
"""


_SQL_PROJECT_TOTAL_MP = """
    SELECT COUNT(*) FROM measurement_points WHERE project_id = :pid
"""


def check_cell_ref_dim(db: Session, project_id: str, key: str) -> CellRefDimStatus:
    """Vérifie si ``group_by=<key>`` est utilisable pour ce projet.

    Renvoie ``available=False`` + ``reason`` lorsque le join ne remonte
    aucune valeur — on ne fabrique JAMAIS un groupe « probable ».
    """
    col = CELL_REF_DIMS.get(key)
    if col is None:
        return CellRefDimStatus(
            key=key, available=False,
            reason=f"group_by {key!r} non pris en charge (clés : {sorted(CELL_REF_DIMS)!r})",
            n_with_value=0, n_total_mp=0,
        )
    n_total_mp = int(
        db.execute(text(_SQL_PROJECT_TOTAL_MP), {"pid": project_id}).scalar() or 0
    )
    sql = _SQL_DIM_COVERAGE.format(col=col)
    row = db.execute(text(sql), {"pid": project_id}).first()
    n_with_value = int(row[0]) if row and row[0] is not None else 0
    label = _LABEL_FR.get(key, key)
    if n_total_mp == 0:
        return CellRefDimStatus(
            key=key, available=False,
            reason="aucun measurement_point sur ce projet",
            n_with_value=0, n_total_mp=0,
        )
    if n_with_value == 0:
        return CellRefDimStatus(
            key=key, available=False,
            reason=f"référentiel cellule non chargé ({label.lower()})",
            n_with_value=0, n_total_mp=n_total_mp,
        )
    return CellRefDimStatus(
        key=key, available=True, reason=None,
        n_with_value=n_with_value, n_total_mp=n_total_mp,
    )


def build_group_by_options(db: Session, project_id: str) -> list[dict[str, Any]]:
    """Retourne la liste complète des ``group_by`` utilisables pour ce
    projet. ``operator`` / ``band`` / ``operator_band`` sont toujours
    disponibles ; les dimensionnels sont checkés via
    :func:`check_cell_ref_dim`.
    """
    out: list[dict[str, Any]] = [
        {"key": "operator",      "available": True, "reason": None},
        {"key": "band",          "available": True, "reason": None},
        {"key": "operator_band", "available": True, "reason": None},
    ]
    for key in CELL_REF_DIMS:
        st = check_cell_ref_dim(db, project_id, key)
        out.append(
            {"key": st.key, "available": st.available, "reason": st.reason}
        )
    return out


def param_occurrence_dim_counts(
    db: Session, project_id: str, param_key: str, group_by_key: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pour une ``param_key`` donnée et un ``group_by`` dimensionnel,
    renvoie :
      - rows ``[{value, dim, n}]`` (dim = libellé DOR / DR / …, ``'N/D'``
        pour les points sans ECGI strict ou sans valeur dans cell_ref).
      - coverage ``{with_value, total}`` sur le ``param_occurrence``
        filtré (sommé toutes valeurs confondues).

    La jointure se fait via ``stg_event_id → measurement_points`` dans
    la même capture (pas de supposition cross-capture).
    """
    col = CELL_REF_DIMS[group_by_key]
    sql = f"""
        WITH po AS (
            SELECT po.id, po.stg_event_id,
                   COALESCE(po.value_converted, po.value) AS v
            FROM param_occurrence po
            WHERE po.project_id = :pid AND po.param_key = :k
              AND COALESCE(po.value_converted, po.value) IS NOT NULL
        ),
        mp_strict AS (
            SELECT stg_event_id, ecgi
            FROM measurement_points
            WHERE project_id = :pid
              AND ecgi IS NOT NULL
              AND ecgi_source = 'sib1_strict_capture_earfcn'
        ),
        joined AS (
            SELECT po.v,
                   mp.ecgi,
                   cr.{col} AS dim_val
            FROM po
            LEFT JOIN mp_strict mp USING (stg_event_id)
            LEFT JOIN cell_ref cr ON cr.eci = mp.ecgi
        )
        SELECT v,
               COALESCE(dim_val, 'N/D') AS dim,
               COUNT(*) AS n,
               SUM(CASE WHEN dim_val IS NOT NULL THEN 1 ELSE 0 END) AS with_value
        FROM joined
        GROUP BY v, COALESCE(dim_val, 'N/D')
        ORDER BY v
    """
    rows = db.execute(text(sql), {"pid": project_id, "k": param_key}).fetchall()
    out_rows: list[dict[str, Any]] = []
    cov_with = 0
    cov_total = 0
    for r in rows:
        v, dim, n, with_value = r[0], r[1], int(r[2]), int(r[3] or 0)
        out_rows.append({"value": str(v), "dim": dim, "n": n})
        cov_with += with_value
        cov_total += n
    coverage = {"with_value": cov_with, "total": cov_total}
    return out_rows, coverage


def mp_metric_dim_percentiles(
    db: Session, project_id: str, mp_col: str, group_by_key: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Percentile P10/P50/P90 par dimension cell_ref pour un KPI mesuré
    sur ``measurement_points.<mp_col>``. ``N/D`` pour les points sans
    ECGI strict ou sans valeur dans cell_ref — jamais filtré."""
    col = CELL_REF_DIMS[group_by_key]
    sql = f"""
        WITH joined AS (
            SELECT mp.{mp_col} AS v,
                   CASE
                       WHEN mp.ecgi IS NOT NULL
                            AND mp.ecgi_source = 'sib1_strict_capture_earfcn'
                       THEN cr.{col}
                       ELSE NULL
                   END AS dim_val
            FROM measurement_points mp
            LEFT JOIN cell_ref cr ON cr.eci = mp.ecgi
            WHERE mp.project_id = :pid AND mp.{mp_col} IS NOT NULL
        )
        SELECT COALESCE(dim_val, 'N/D') AS dim,
               COUNT(*) AS n,
               percentile_cont(0.10) WITHIN GROUP (ORDER BY v) AS p10,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY v) AS p50,
               percentile_cont(0.90) WITHIN GROUP (ORDER BY v) AS p90,
               SUM(CASE WHEN dim_val IS NOT NULL THEN 1 ELSE 0 END) AS with_value
        FROM joined
        GROUP BY COALESCE(dim_val, 'N/D')
        ORDER BY COALESCE(dim_val, 'N/D')
    """
    rows = db.execute(text(sql), {"pid": project_id}).fetchall()
    out: list[dict[str, Any]] = []
    cov_with = 0
    cov_total = 0
    for r in rows:
        dim, n, p10, p50, p90, with_value = r
        out.append({
            group_by_key: dim,
            "n":          int(n),
            "p10":        float(p10) if p10 is not None else None,
            "p50":        float(p50) if p50 is not None else None,
            "p90":        float(p90) if p90 is not None else None,
        })
        cov_with += int(with_value or 0)
        cov_total += int(n)
    coverage = {"with_value": cov_with, "total": cov_total}
    return out, coverage
