"""Restore primary keys required by idempotent application seeds."""

from alembic import op
import sqlalchemy as sa


revision = "0046_seed_pkeys"
down_revision = "0045_settings_pkeys"
branch_labels = None
depends_on = None


PRIMARY_KEYS = (
    ("users", "id"),
    ("assistant_exec_steps", "id"),
    ("geo_references", "id"),
    ("kpi_catalog", "code"),
    ("kpi_catalog_groups", "name"),
    ("kpi_rrc_summary", "id"),
    ("projects", "id"),
    ("dict_messages", "msg_id"),
    ("dict_params", "param_id"),
    ("conversion_rule", "param_id"),
)


def upgrade() -> None:
    for table, column in PRIMARY_KEYS:
        primary_key = sa.inspect(op.get_bind()).get_pk_constraint(table)
        if not primary_key.get("constrained_columns"):
            op.create_primary_key(f"{table}_pkey", table, [column])


def downgrade() -> None:
    # These constraints are also created by 0001 on a fresh database.  A
    # downgrade must not remove baseline primary keys.
    pass
