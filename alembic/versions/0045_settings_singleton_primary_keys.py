"""Restore primary keys for singleton settings tables."""

from alembic import op
import sqlalchemy as sa


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
        # Fresh databases already receive these primary keys from 0001.  Some
        # imported legacy schemas did not, which is why this repair migration
        # exists.  Inspect the actual constraint instead of assuming either
        # schema history.
        primary_key = sa.inspect(op.get_bind()).get_pk_constraint(table)
        if not primary_key.get("constrained_columns"):
            op.create_primary_key(f"{table}_pkey", table, ["id"])


def downgrade() -> None:
    # The same named constraints can belong to the 0001 baseline.  Dropping
    # them here would corrupt a fresh-schema downgrade, so this repair is
    # intentionally irreversible.
    pass
