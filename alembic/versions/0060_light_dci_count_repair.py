"""Repair the replayed Light schema required by decoder 1.7.1.

Revision ID: 0060_light_dci_count_repair
Revises: 0059_project_parsing_defaults
"""

from alembic import op


revision = "0060_light_dci_count_repair"
down_revision = "0059_project_parsing_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Databases stamped past 0052 before its replay repair was merged do not
    # execute that old migration again. This closes that historical gap.
    op.execute(
        'ALTER TABLE nmf_event_light '
        'ADD COLUMN IF NOT EXISTS "dci_dci_count" DOUBLE PRECISION'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE nmf_event_light '
        'DROP COLUMN IF EXISTS "dci_dci_count"'
    )
