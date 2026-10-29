"""decoder 1.8.1: persist NFF 2.50 PLAIU serving-cell discriminator.

Revision ID: bc1_decoder_1_8_1_cells
Revises: bc1_light_native_sparse
"""
from alembic import op


revision = "bc1_decoder_1_8_1_cells"
down_revision = "bc1_light_native_sparse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("nmf_event_deep", "nmf_event_light"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS plaiu_cell_type DOUBLE PRECISION"
        )


def downgrade() -> None:
    for table in ("nmf_event_light", "nmf_event_deep"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS plaiu_cell_type")
