"""decoder 1.7.0 light group cols

Revision ID: 0054_light_group_1_7_0
Revises: 0053_decoder_1_7_0_nr_cols
Create Date: 2026-10-25

Fix post-0053 : les codes `cell.*` des groupes NR (CELLMEAS_NR,
MIMOMEAS_NR) sont PROPAGÉS au bucket Light principal via la boucle
`for f in definition['fields']: add(column(f['code']),...)` dans
light.py (branche sans `aggregate_selection=first`). Donc chaque
code `cell.bi`, `cell.meas_type`, `cell.port`, `cell.*_fil`, `cell.*_p`,
`cell.sinr`, `cell.to`, `cell.extra_1/2` doit aussi exister dans
`nmf_event_light` (pas seulement dans `nmf_event_light_group`).

L'incident 2026-10-25 16:30 : la 1re capture UE NR (134af70a06eb/
1e4e8d879a83) a échoué avec `UndefinedColumn: column "cell_bi" of
relation "nmf_event_light" does not exist`.
"""
from alembic import op

revision = '0054_light_group_1_7_0'
down_revision = '0053_decoder_1_7_0_nr_cols'
branch_labels = None
depends_on = None

COLS = [
    'cell_bi','cell_extra_1','cell_extra_2','cell_meas_type','cell_port',
    'cell_rsrp_fil','cell_rsrp_p','cell_rsrq_fil','cell_rsrq_p','cell_rssi_p',
    'cell_sinr','cell_sinr_fil','cell_sinr_p','cell_to',
]


def upgrade():
    for col in COLS:
        op.execute(f'ALTER TABLE nmf_event_light ADD COLUMN IF NOT EXISTS {col} double precision')


def downgrade():
    for col in COLS:
        op.execute(f'ALTER TABLE nmf_event_light DROP COLUMN IF EXISTS {col}')
