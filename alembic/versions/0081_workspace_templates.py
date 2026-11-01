"""Add durable, user-isolated KPI workspace templates.

Revision ID: 0081_workspace_templates
Revises: 0080_superstream_ss01

This migration only creates template metadata. It never reads or changes NMF,
capture, event, KPI or measurement data.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0081_workspace_templates"
down_revision = "0080_superstream_ss01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_template",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_workspace_template_revision_positive"
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_workspace_template_schema_positive"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_template_project_owner",
        "workspace_template",
        ["project_id", "owner_id"],
    )
    op.create_index(
        "uq_workspace_template_project_owner_name_ci",
        "workspace_template",
        ["project_id", "owner_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workspace_template_project_owner_name_ci",
        table_name="workspace_template",
    )
    op.drop_index(
        "ix_workspace_template_project_owner", table_name="workspace_template"
    )
    op.drop_table("workspace_template")
