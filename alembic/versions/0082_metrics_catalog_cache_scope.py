"""Scope Metrics catalogue cache rows by project and capture set.

Revision ID: 0082_metrics_catalog_cache_scope
Revises: 0081_workspace_templates
"""
from alembic import op


revision = "0082_metrics_catalog_cache_scope"
down_revision = "0081_workspace_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE metrics_catalog_cache "
        "ADD COLUMN scope_key text NOT NULL DEFAULT 'project'"
    )
    op.execute("ALTER TABLE metrics_catalog_cache DROP CONSTRAINT metrics_catalog_cache_pkey")
    op.execute(
        "ALTER TABLE metrics_catalog_cache ADD CONSTRAINT metrics_catalog_cache_pkey "
        "PRIMARY KEY (project_id, scope_key)"
    )


def downgrade():
    op.execute("DELETE FROM metrics_catalog_cache WHERE scope_key <> 'project'")
    op.execute("ALTER TABLE metrics_catalog_cache DROP CONSTRAINT metrics_catalog_cache_pkey")
    op.execute(
        "ALTER TABLE metrics_catalog_cache ADD CONSTRAINT metrics_catalog_cache_pkey "
        "PRIMARY KEY (project_id)"
    )
    op.execute("ALTER TABLE metrics_catalog_cache DROP COLUMN scope_key")
