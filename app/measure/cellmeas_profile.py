"""Table `cellmeas_profile` : trace versionnée du profil CELLMEAS (0.44.0).

Doctrine (G5) :
- Un chiffre affiché côté KPI vient d'un champ CELLMEAS choisi par la
  **preuve** (`prove_rsrp_per_event`), pas par une heuristique moyenne.
- Chaque profil est **persisté** par `(project_id, capture_id, metric,
  decoder_release)` → traçabilité stable même si on repopule.
- `populate_measurement_points` **refuse** de populer si le verdict RSRP
  n'est pas `proven` : NULL déclaré plutôt que valeur douteuse.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


# -----------------------------------------------------------------------
# DDL
# -----------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS cellmeas_profile (
    id              BIGSERIAL PRIMARY KEY,
    project_id      VARCHAR  NOT NULL,
    capture_id      VARCHAR,
    metric          VARCHAR  NOT NULL,
    field           VARCHAR,
    avg             DOUBLE PRECISION,
    n               INTEGER,
    n_pairs         INTEGER,
    median_abs_delta DOUBLE PRECISION,
    p90_abs_delta   DOUBLE PRECISION,
    verdict         VARCHAR  NOT NULL,
    reason          TEXT,
    decoder_release VARCHAR,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_cmp_pid_metric
    ON cellmeas_profile (project_id, metric, created_at DESC);
"""


def ensure_table(db: Session) -> None:
    """Crée la table (idempotent). À appeler en tête de
    `populate_measurement_points`."""
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            db.execute(text(s))
    db.commit()


# -----------------------------------------------------------------------
# Persist
# -----------------------------------------------------------------------
def persist_profile_row(
    db: Session,
    *,
    project_id: str,
    metric: str,
    field: str | None,
    avg: float | None,
    n: int,
    n_pairs: int | None,
    median_abs_delta: float | None,
    p90_abs_delta: float | None,
    verdict: str,
    reason: str | None,
    decoder_release: str = "bc4-decoder 2.0.0",
    capture_id: str | None = None,
) -> None:
    """Insère UNE ligne de profil. Pas d'UPDATE : chaque run empile sa
    version — on garde l'historique (ORDER BY created_at DESC)."""
    db.execute(
        text(
            """
            INSERT INTO cellmeas_profile
                (project_id, capture_id, metric, field, avg, n, n_pairs,
                 median_abs_delta, p90_abs_delta, verdict, reason,
                 decoder_release, created_at)
            VALUES (:pid, :cap, :m, :f, :avg, :n, :np, :mad, :p90,
                    :v, :reason, :dr, :created)
            """
        ),
        {
            "pid": project_id,
            "cap": capture_id,
            "m": metric,
            "f": field,
            "avg": avg,
            "n": n,
            "np": n_pairs,
            "mad": median_abs_delta,
            "p90": p90_abs_delta,
            "v": verdict,
            "reason": reason,
            "dr": decoder_release,
            "created": datetime.now(tz=timezone.utc),
        },
    )
    db.commit()
