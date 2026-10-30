"""Index exact radio identities in the cell reference.

Revision ID: 0076_map_cell_links
Revises: 0075_decoder_1_9_0_plaiu
"""
from alembic import op


revision = "0076_map_cell_links"
down_revision = "0075_decoder_1_9_0_plaiu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("""CREATE INDEX CONCURRENTLY ix_cell_ref_radio_identity
          ON cell_ref (earfcn,pci,techno)
          INCLUDE (id,site_id,site_name)
          WHERE geom IS NOT NULL""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cell_ref_radio_identity")
