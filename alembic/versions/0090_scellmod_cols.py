"""Decoder 1.10.8 — add scellmod_* columns for SCELLMOD.

SCELLMOD NFF 2.50 p.424-429 : header 2 fields (#Header params + Result).
Groups : added SCells ({Cell type, Band, ARFCN, PCI}) + removed SCells
({Cell type, Band, ARFCN, PCI}).
"""
from alembic import op
import sqlalchemy as sa

revision = '0090_scellmod_cols'
down_revision = '0089_dci_nr_cols'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light', 'nmf_event_deep', 'nmf_event_light_group', 'nmf_event_group')

NEW_COLS = (
    'scellmod_n_params',
    'scellmod_result',
    'scellmod_cell_type',
    'scellmod_added_band',
    'scellmod_added_arfcn',
    'scellmod_added_pci',
    'scellmod_removed_band',
    'scellmod_removed_arfcn',
    'scellmod_removed_pci',
    'scellmod_n_scells_added',
    'scellmod_params_per_added',
    'scellmod_n_scells_removed',
    'scellmod_params_per_removed',
)

def upgrade():
    for t in TABLES:
        for col in NEW_COLS:
            op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} FLOAT")

def downgrade():
    for t in TABLES:
        for col in reversed(NEW_COLS):
            op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {col}")
