"""Indexes for capture-scoped Signaling View projections.

Revision ID: 0041_sig_idx
Revises: 0040_metrics_catalog_cache
"""
from alembic import op

revision = "0041_sig_idx"
down_revision = "0040_metrics_catalog_cache"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE INDEX IF NOT EXISTS ix_stg_event_project_capture_code_seq
        ON stg_event (project_id, capture_id, event_code, seq)"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS ix_stg_event_raw_project_capture_code_seq
        ON stg_event_raw (project_id, capture_id, event_code, seq)"""
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_stg_event_project_capture_code_seq")
    op.execute("DROP INDEX IF EXISTS ix_stg_event_raw_project_capture_code_seq")
