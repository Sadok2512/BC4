"""Decoder 1.10.7 — add dci_scope + dci_cce_aggr_level + dci_format_count +
dci_cce_count + dci_cce_n_variables + dci_cce_params_variable columns for DCI NR.

DCI NR NFF 2.50 p.553-555 : header 6 fields (#Header params + Scope + Cell type
+ CCE aggregation level + UL grants + DL grants). Groups : DCI format
distribution ({Count, DCI format}) + CCE aggregation level distribution
({Count, CCE aggregation level}).

LTE schema has 9 header fields and no Scope/CCE aggregation level.
"""
from alembic import op
import sqlalchemy as sa

revision = '0089_dci_nr_cols'
down_revision = '0088_cqi_nr_scope_count'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light', 'nmf_event_deep', 'nmf_event_light_group', 'nmf_event_group')

NEW_COLS = (
    'dci_n_params',
    'dci_n_variables',
    'dci_params_variable',
    'dci_scope',
    'dci_cce_aggr_level',
    'dci_format_count',
    'dci_cce_count',
    'dci_cce_n_variables',
    'dci_cce_params_variable',
)

def upgrade():
    for t in TABLES:
        for col in NEW_COLS:
            op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} FLOAT")

def downgrade():
    for t in TABLES:
        for col in reversed(NEW_COLS):
            op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {col}")
