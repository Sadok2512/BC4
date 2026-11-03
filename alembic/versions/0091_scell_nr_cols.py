"""Decoder 1.11.0 — add scell_* columns for SCELL NR serving cells group.

SCELL NR NFF 2.50 p.345-349 : header 5 fields + serving_cells group (16 params
per cell, count at header col 6, params at header col 7, data starts at col 10
— layout header-interleaved supporté par le nouveau count_header_col/params_header_col).
"""
from alembic import op
import sqlalchemy as sa

revision = '0091_scell_nr_cols'
down_revision = '0090_scellmod_cols'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light', 'nmf_event_deep', 'nmf_event_light_group', 'nmf_event_group')

NEW_COLS = (
    'scell_n_params',
    'scell_n_serving_cells',
    'scell_params_per_sc',
    'scell_params_per_bwp',
    'scell_c_rnti',
    'scell_cell_type',
    'scell_ssb_band',
    'scell_ssb_nr_arfcn',
    'scell_pci',
    'scell_dl_pointa',
    'scell_ul_pointa',
    'scell_dss_lte_offset',
    'scell_dss_lte_bw',
    'scell_ssb_periodicity',
    'scell_n_bwps',
    'scell_n_serving_cells_g',
    'scell_params_per_sc_g',
)

def upgrade():
    for t in TABLES:
        for col in NEW_COLS:
            op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} FLOAT")

def downgrade():
    for t in TABLES:
        for col in reversed(NEW_COLS):
            op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {col}")
