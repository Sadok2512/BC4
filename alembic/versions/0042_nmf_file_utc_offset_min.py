"""Add nmf_file.utc_offset_min (minutes, signed local-UTC) from NMF header #UT col 1.

NFF 2.19 : #UT col 1 = "UTC_to_local" en minutes, signe `local - UTC`
(ex. CEST = +120). Nullable : si le fichier n'a pas d'en-tête `#UT`
l'écart est déclaré, pas inventé.

Revision ID: 0042_utc_offset
Revises: 0041_sig_idx
"""
from alembic import op
import sqlalchemy as sa

revision = "0042_utc_offset"
down_revision = "0041_sig_idx"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "nmf_file",
        sa.Column("utc_offset_min", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("nmf_file", "utc_offset_min")
