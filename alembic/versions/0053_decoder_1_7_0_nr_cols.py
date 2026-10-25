"""decoder 1.7.0 NR columns

Revision ID: 0053_decoder_1_7_0_nr_cols
Revises: 0052_deep_2_50_cols
Create Date: 2026-10-25

Ajoute les colonnes nécessaires aux YAMLs CELLMEAS_NR, MIMOMEAS_NR, TAD_NR,
TXPC_NR, PHRATE_NR (chargés sous `_variants[9]` par schema.py 1.7.0 pour
dispatch LTE/NR).

Headers → nmf_event_light + nmf_event_deep (19 cols) :
  cellmeas_scope, mimomeas_hdr_n, mimomeas_params_per_measurement,
  phrate_cell_type, phrate_hdr_n, phrate_pdsch_sch_bitrate, phrate_scope,
  tad_scope, txpc_cell_type, txpc_f_il, txpc_g_il, txpc_n_pusch_tpc,
  txpc_pucch_pl, txpc_pusch_ph, txpc_pusch_pl, txpc_scope,
  txpc_srs_tx_power, txpc_tx_power, txpc_ul_type.

Groups (cells / measurements NR) → nmf_event_light_group + nmf_event_group
(14 cols) :
  cell_bi, cell_extra_1, cell_extra_2, cell_meas_type, cell_port,
  cell_rsrp_fil, cell_rsrp_p, cell_rsrq_fil, cell_rsrq_p, cell_rssi_p,
  cell_sinr, cell_sinr_fil, cell_sinr_p, cell_to.
"""
from alembic import op

revision = '0053_decoder_1_7_0_nr_cols'
down_revision = '0052_deep_2_50_cols'
branch_labels = None
depends_on = None

HEADER_COLS = [
    'cellmeas_scope','mimomeas_hdr_n','mimomeas_params_per_measurement',
    'phrate_cell_type','phrate_hdr_n','phrate_pdsch_sch_bitrate','phrate_scope',
    'tad_scope','txpc_cell_type','txpc_f_il','txpc_g_il','txpc_n_pusch_tpc',
    'txpc_pucch_pl','txpc_pusch_ph','txpc_pusch_pl','txpc_scope',
    'txpc_srs_tx_power','txpc_tx_power','txpc_ul_type',
]
GROUP_COLS = [
    'cell_bi','cell_extra_1','cell_extra_2','cell_meas_type','cell_port',
    'cell_rsrp_fil','cell_rsrp_p','cell_rsrq_fil','cell_rsrq_p','cell_rssi_p',
    'cell_sinr','cell_sinr_fil','cell_sinr_p','cell_to',
]


def upgrade():
    for col in HEADER_COLS:
        op.execute(f'ALTER TABLE nmf_event_light ADD COLUMN IF NOT EXISTS {col} double precision')
        op.execute(f'ALTER TABLE nmf_event_deep  ADD COLUMN IF NOT EXISTS {col} double precision')
    for col in GROUP_COLS:
        op.execute(f'ALTER TABLE nmf_event_light_group ADD COLUMN IF NOT EXISTS {col} double precision')
        op.execute(f'ALTER TABLE nmf_event_group       ADD COLUMN IF NOT EXISTS {col} double precision')


def downgrade():
    for col in HEADER_COLS:
        op.execute(f'ALTER TABLE nmf_event_light DROP COLUMN IF EXISTS {col}')
        op.execute(f'ALTER TABLE nmf_event_deep  DROP COLUMN IF EXISTS {col}')
    for col in GROUP_COLS:
        op.execute(f'ALTER TABLE nmf_event_light_group DROP COLUMN IF EXISTS {col}')
        op.execute(f'ALTER TABLE nmf_event_group       DROP COLUMN IF EXISTS {col}')
