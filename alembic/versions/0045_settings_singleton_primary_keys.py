"""Restore primary keys for singleton settings tables."""

from alembic import op


revision = "0045_settings_pkeys"
down_revision = "0044_nmf_string_columns"
branch_labels = None
depends_on = None


TABLES = (
    "settings_ai",
    "settings_appearance",
    "settings_llm",
    "settings_organization",
    "settings_password_policy",
    "settings_permissions",
)


def upgrade() -> None:
    for table in TABLES:
        op.create_primary_key(f"{table}_pkey", table, ["id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
