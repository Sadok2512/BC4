"""Index on param_occurrence.stg_event_id — accelerate ON DELETE CASCADE.

Phase 2.2a 10e passe : la 9e passe du re-decode a été tuée à 21:52 parce
que chaque DELETE sur stg_event déclenchait un cascade sur param_occurrence
(1.25M lignes) sans index support. Chaque capture coûtait ~14 min au lieu
de ~3 min. Ajout de l'index pour que la FK cascade soit instantanée.

Revision ID : 0051_param_occurrence_fk_index
Revises    : 0050_light_2_50_cols
"""
from alembic import op

revision = "0051_param_occurrence_fk_index"
down_revision = "0050_light_2_50_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index plain (alembic DDL transactionnel refuse CONCURRENTLY).
    # Table 1.25M lignes → verrouillage ~30s acceptable sous DEPLOY_LOCK.
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_param_occurrence_stg_event_id "
        "ON param_occurrence (stg_event_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_param_occurrence_stg_event_id")
