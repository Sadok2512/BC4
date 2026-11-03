"""Decoder 1.10.6 — add cqi_scope + cqi_cell_type + cqi_ri_count + cqi_wb_cqi_count columns for CQI NR.

CQI NR NFF 2.50 p.579-580 : header has #Header params + Scope + Cell type +
RI + WB CQI. Groups : RI distribution ({Count, RI}) + WB CQI distribution
({Count, WB CQI}). LTE schema has no Scope/Cell type and uses different
group field names.
"""
from alembic import op
import sqlalchemy as sa

revision = '0088_cqi_nr_scope_count'
down_revision = '0087_macrate_nr_scope'
branch_labels = None
depends_on = None

LIGHT_TABLES = ('nmf_event_light', 'nmf_event_deep')
GROUP_TABLES = ('nmf_event_light_group', 'nmf_event_group')

def upgrade():
    # Toutes les colonnes doivent exister dans light ET group tables car le
    # décodeur réfléchit le payload entier (y compris les group fields)
    # dans nmf_event_light pour la variante header-flat.
    for t in LIGHT_TABLES + GROUP_TABLES:
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS cqi_scope FLOAT")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS cqi_cell_type FLOAT")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS cqi_ri_count FLOAT")
        op.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS cqi_wb_cqi_count FLOAT")

def downgrade():
    for t in LIGHT_TABLES:
        op.drop_column(t, 'cqi_scope')
        op.drop_column(t, 'cqi_cell_type')
    for t in GROUP_TABLES:
        op.drop_column(t, 'cqi_wb_cqi_count')
        op.drop_column(t, 'cqi_ri_count')
        op.drop_column(t, 'cqi_cell_type')
        op.drop_column(t, 'cqi_scope')
