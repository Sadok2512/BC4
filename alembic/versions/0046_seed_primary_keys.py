"""Restore primary keys required by idempotent application seeds."""

from alembic import op


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
        op.create_primary_key(f"{table}_pkey", table, [column])


def downgrade() -> None:
    for table, _column in reversed(PRIMARY_KEYS):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
