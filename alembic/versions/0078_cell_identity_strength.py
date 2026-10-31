"""Persist CELLMEAS RSRP used to rank probable neighbour links.

Revision ID: 0078_cell_identity_strength
Revises: 0077_cell_ref_band_channels
"""
from alembic import op
import sqlalchemy as sa


revision = "0078_cell_identity_strength"
down_revision = "0077_cell_ref_band_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nmf_cell_identity", sa.Column("cell_rsrp", sa.Float(), nullable=True))
    op.execute("""
        UPDATE nmf_cell_identity i
        SET cell_rsrp=s.cell_rsrp
        FROM (
          SELECT project_id,capture_id,seq_first,event_code,cell_index,
                 MAX(value) AS cell_rsrp
          FROM nmf_cell_second
          WHERE metric_code='cell_rsrp'
          GROUP BY project_id,capture_id,seq_first,event_code,cell_index
        ) s
        WHERE s.project_id=i.project_id AND s.capture_id=i.capture_id
          AND s.seq_first=i.seq AND s.event_code=i.event_code
          AND s.cell_index=i.cell_index
    """)


def downgrade() -> None:
    op.drop_column("nmf_cell_identity", "cell_rsrp")
