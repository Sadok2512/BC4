"""0.46.0 — projects.last_populate_at + projects.n_points

Suivi complétude ingest↔populate. Deux colonnes nullables sur `projects` :

- ``last_populate_at`` TIMESTAMPTZ : horodatage du dernier `populate_full`
  réussi (chaîne `populate_measurements → populate_measurement_points →
  populate_ecgi_for_project`). NULL = jamais passé.
- ``n_points`` INTEGER : COUNT(mp) après le populate (snapshot). NULL si
  aucun populate n'a tourné.

Dérivé par la route ``GET /projects`` (champ `ingest_status`) :
  - `nmf_file.status='done' COUNT = 0`         → `empty`
  - nmf_count>0 ET (last_populate_at NULL      → `incomplete`
                    OU n_points = 0)
  - sinon                                      → `ready`

Discipline additive stricte : aucune colonne existante modifiée. Les projets
B0 (seeds) et B1 historiques sortent `last_populate_at=NULL, n_points=NULL,
ingest_status='incomplete'` tant qu'un populate n'a pas tourné.

Revision ID: 0018_project_populate_tracking
Revises: 0017_param_occurrence_dict_v2
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018_project_populate_tracking"
down_revision: str | None = "0017_param_occurrence_dict_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("last_populate_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("n_points", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "n_points")
    op.drop_column("projects", "last_populate_at")
