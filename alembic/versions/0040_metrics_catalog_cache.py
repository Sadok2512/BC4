"""Persistent project-scoped cache for the expensive metrics catalogue.

Revision ID: 0040_metrics_catalog_cache
Revises: 0039_decoder_lock_fields
"""
from alembic import op

revision = "0040_metrics_catalog_cache"
down_revision = "0039_decoder_lock_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE metrics_catalog_cache (
        project_id varchar PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        decode_stamp text NOT NULL,
        payload jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )""")


def downgrade():
    op.execute("DROP TABLE metrics_catalog_cache")
