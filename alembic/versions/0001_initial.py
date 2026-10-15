"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Prepare PostGIS for B1 (not used in B0 but the extension must exist).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("login", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("geography", sa.String(), nullable=False),
        sa.Column("center_lng", sa.Float(), nullable=False),
        sa.Column("center_lat", sa.Float(), nullable=False),
        sa.Column("operators", sa.JSON(), nullable=False),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("bands", sa.JSON(), nullable=False),
        sa.Column("departements", sa.JSON(), nullable=False),
        sa.Column("period_start", sa.String(), nullable=False),
        sa.Column("period_end", sa.String(), nullable=False),
        sa.Column("captures", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )

    op.create_table(
        "measurement_points",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("operator", sa.String(), nullable=False, index=True),
        sa.Column("tech", sa.String(), nullable=False, index=True),
        sa.Column("service", sa.String(), nullable=False, index=True),
        sa.Column("band", sa.String(), nullable=False, index=True),
        sa.Column("dep", sa.String(), nullable=False, index=True),
        sa.Column("site", sa.String(), nullable=False),
        sa.Column("ts", sa.String(), nullable=False),
        sa.Column("dl", sa.Float(), nullable=True),
        sa.Column("rsrp", sa.Float(), nullable=True),
        sa.Column("sinr", sa.Float(), nullable=True),
        sa.Column("latency", sa.Float(), nullable=True),
        sa.Column("capture_id", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
    )

    op.create_table(
        "dict_messages",
        sa.Column("msg_id", sa.String(), primary_key=True),
        sa.Column("techno", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
    )

    op.create_table(
        "dict_params",
        sa.Column("param_id", sa.String(), primary_key=True),
        sa.Column("msg_id", sa.String(), sa.ForeignKey("dict_messages.msg_id"), nullable=False, index=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("leaf", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("has_gps", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("simulate_error", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spec_kind", sa.String(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
    )

    op.create_table(
        "conversion_rule",
        sa.Column("param_id", sa.String(), sa.ForeignKey("dict_params.param_id"), primary_key=True),
        sa.Column("formula", sa.String(), nullable=False),
        sa.Column("scale", sa.Float(), nullable=False),
        sa.Column("offset", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
    )

    op.create_table(
        "rrc_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("param_id", sa.String(), sa.ForeignKey("dict_params.param_id"), nullable=False, index=True),
        sa.Column("operator", sa.String(), nullable=False, index=True),
        sa.Column("band", sa.String(), nullable=False, index=True),
        sa.Column("service", sa.String(), nullable=False, index=True),
        sa.Column("dep", sa.String(), nullable=False, index=True),
        sa.Column("raw_num", sa.Float(), nullable=True),
        sa.Column("raw_str", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("capture_id", sa.String(), nullable=True, index=True),
        sa.Column("seq", sa.Integer(), nullable=True),
    )

    op.create_table(
        "kpi_catalog",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("family", sa.String(), nullable=False),
        sa.Column("tech", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_events", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
    )

    op.create_table(
        "kpi_catalog_groups",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "kpi_rrc_summary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("techs", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("by_op", sa.JSON(), nullable=False),
    )

    op.create_table(
        "settings_appearance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_primary_hex", sa.String(), nullable=True),
    )

    op.create_table(
        "settings_organization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("short_name", sa.String(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("logo_data_url", sa.Text(), nullable=True),
        sa.Column("admin_contact", sa.String(), nullable=False, server_default=""),
        sa.Column("domain", sa.String(), nullable=False, server_default=""),
        sa.Column("show_in_header", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_in_exports", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("name_max", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("logo_max_bytes", sa.Integer(), nullable=False, server_default="300000"),
        sa.Column("logo_types", sa.JSON(), nullable=False),
    )

    op.create_table(
        "settings_password_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("min_length", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("require_digit", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("require_upper", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "settings_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("editor_can_edit_geo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("editor_can_edit_kpi", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "settings_ai",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("endpoint_url", sa.String(), nullable=False, server_default=""),
        sa.Column("model_code", sa.String(), nullable=False, server_default=""),
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("providers", sa.JSON(), nullable=False),
        sa.Column("auth_method", sa.String(), nullable=False, server_default="api_key"),
        sa.Column("has_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("saved_at", sa.String(), nullable=True),
        sa.Column("connection", sa.JSON(), nullable=False),
    )

    op.create_table(
        "assistant_exec_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )

    op.create_table(
        "geo_references",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("imported_at", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for t in (
        "geo_references",
        "assistant_exec_steps",
        "settings_ai",
        "settings_permissions",
        "settings_password_policy",
        "settings_organization",
        "settings_appearance",
        "kpi_rrc_summary",
        "kpi_catalog_groups",
        "kpi_catalog",
        "rrc_observations",
        "conversion_rule",
        "dict_params",
        "dict_messages",
        "measurement_points",
        "projects",
        "users",
    ):
        op.drop_table(t)
