"""Persist the complete NFF 2.50 LTE PLAIU repeated fields.

Revision ID: 0075_decoder_1_9_0_plaiu
Revises: 0074_auth_password_change
"""
from alembic import op


revision = "0075_decoder_1_9_0_plaiu"
down_revision = "0074_auth_password_change"
branch_labels = None
depends_on = None


GROUP_COLUMNS = (
    "plaiu_mod1",
    "plaiu_mcs1",
    "plaiu_n_rep",
    "plaiu_tbs0",
    "plaiu_tbs1",
    "plaiu_scs",
)


def upgrade() -> None:
    # Repeated values are aggregated into nmf_event_light as well as retained
    # in both group tables. These are column additions only; no index is built.
    for column in GROUP_COLUMNS:
        for table in ("nmf_event_light", "nmf_event_light_group", "nmf_event_group"):
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION"
            )


def downgrade() -> None:
    for column in reversed(GROUP_COLUMNS):
        for table in ("nmf_event_group", "nmf_event_light_group", "nmf_event_light"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
