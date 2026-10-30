"""Separate cell-reference band MHz from exact LTE/NR channels.

Revision ID: 0077_cell_ref_band_channels
Revises: 0076_map_cell_links

The former ``cell_ref.earfcn`` mixed a band-frequency label with exact LTE/NR
channels. ``band_mhz`` is reconstructed from authoritative ``band_src``.
An old channel is preserved only when it differs from that row's proven band;
equal values (including the ambiguous 1800 case) are cleared and recovered by
the guarded source-file reimport.
"""
from alembic import op
import sqlalchemy as sa


revision = "0077_cell_ref_band_channels"
down_revision = "0076_map_cell_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cell_ref", sa.Column("band_mhz", sa.Integer(), nullable=True))
    op.add_column("cell_ref", sa.Column("nr_arfcn", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE cell_ref
        SET band_mhz = CASE upper(band_src)
          WHEN 'LTE700' THEN 700 WHEN 'LTE800' THEN 800
          WHEN 'LTE900' THEN 900 WHEN 'LTE1800' THEN 1800
          WHEN 'LTE2100' THEN 2100 WHEN 'LTE2600' THEN 2600
          WHEN 'NR_700' THEN 700 WHEN 'NR_1400' THEN 1400
          WHEN 'NR_1800' THEN 1800 WHEN 'NR_2100' THEN 2100
          WHEN 'NR_2600' THEN 2600 WHEN 'NR_3500' THEN 3500
          WHEN 'NR_26_GHZ_000' THEN 26000
          ELSE NULL
        END
    """)
    # A value that differs from the authoritative band on the same row is an
    # exact channel already recovered by 0.115.1. NR-ARFCNs above 100000 are
    # also outside the MHz-band-label domain and remain exact even when a
    # legacy row lacks band_src or carries the historical default LTE label.
    # Equal values are ambiguous (e.g. 1800) and
    # deliberately cleared until traced source reimport.
    op.execute("""
        UPDATE cell_ref
        SET nr_arfcn = CASE
              WHEN earfcn > 100000
                OR (upper(COALESCE(techno, rat)) IN ('5G', 'NR')
                    AND band_mhz IS NOT NULL AND earfcn <> band_mhz)
              THEN earfcn ELSE NULL END,
            earfcn = CASE
              WHEN upper(COALESCE(techno, rat)) IN ('4G', 'LTE')
               AND band_mhz IS NOT NULL AND earfcn <> band_mhz
              THEN earfcn ELSE NULL END
    """)
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cell_ref_radio_identity")
        op.execute("""CREATE INDEX CONCURRENTLY ix_cell_ref_lte_radio_identity
          ON cell_ref (earfcn,pci)
          INCLUDE (id,site_id,site_name)
          WHERE geom IS NOT NULL AND earfcn IS NOT NULL""")
        op.execute("""CREATE INDEX CONCURRENTLY ix_cell_ref_nr_radio_identity
          ON cell_ref (nr_arfcn,pci)
          INCLUDE (id,site_id,site_name)
          WHERE geom IS NOT NULL AND nr_arfcn IS NOT NULL""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cell_ref_nr_radio_identity")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cell_ref_lte_radio_identity")
    op.execute("UPDATE cell_ref SET earfcn = COALESCE(earfcn, nr_arfcn, band_mhz)")
    op.drop_column("cell_ref", "nr_arfcn")
    op.drop_column("cell_ref", "band_mhz")
    with op.get_context().autocommit_block():
        op.execute("""CREATE INDEX CONCURRENTLY ix_cell_ref_radio_identity
          ON cell_ref (earfcn,pci,techno)
          INCLUDE (id,site_id,site_name)
          WHERE geom IS NOT NULL""")
