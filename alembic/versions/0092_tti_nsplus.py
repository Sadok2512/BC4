"""Decoder 1.12.0 — typed TTI_NSPLUS extension fields."""
from alembic import op


revision = "0092_tti_nsplus"
down_revision = "0091_scell_nr_cols"
branch_labels = None
depends_on = None

TABLES = ("nmf_event_light", "nmf_event_deep")
NUMERIC_COLUMNS = (
    "tti_frame_idx",
    "tti_sfn",
    "tti_subfn",
    "tti_carrier",
    "tti_rnti",
    "tti_mcs",
    "tti_prb",
    "tti_tbs_bytes",
    "tti_crc_ok",
    "tti_harq_id",
    "tti_rv",
)


def upgrade():
    for table in TABLES:
        for column in NUMERIC_COLUMNS:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} DOUBLE PRECISION"
            )
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tti_rat TEXT")


def downgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tti_rat")
        for column in reversed(NUMERIC_COLUMNS):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
