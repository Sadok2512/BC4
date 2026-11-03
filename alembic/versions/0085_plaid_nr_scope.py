"""Decoder 1.10.0 — add plaid_scope column for PLAID NR header param #2 (Scope).

The LTE PLAID schema has no Scope field (NFF 2.19 schema). The NR variant
introduces one (NFF 2.50 PLAID NR p.561 #2) that links measurement events
with the same name so the latest instance replaces previous values. Add
the column across the 4 nmf_event_light tables that carry PLAID rows.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '0085_plaid_nr_scope'
down_revision = '0084_cell_srxlev'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light','nmf_event_deep','nmf_event_light_group','nmf_event_group')

def upgrade():
    for t in TABLES:
        op.add_column(t, sa.Column('plaid_scope', sa.Float()))

def downgrade():
    for t in TABLES:
        op.drop_column(t, 'plaid_scope')
