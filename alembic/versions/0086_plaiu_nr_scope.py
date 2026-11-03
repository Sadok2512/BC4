"""Decoder 1.10.2 — add plaiu_scope column for PLAIU NR header param #2 (Scope).

NFF 2.50 PLAIU NR p.570 #2. The LTE PLAIU schema has no Scope field.
"""
from alembic import op
import sqlalchemy as sa

revision = '0086_plaiu_nr_scope'
down_revision = '0085_plaid_nr_scope'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light','nmf_event_deep','nmf_event_light_group','nmf_event_group')

def upgrade():
    for t in TABLES:
        op.add_column(t, sa.Column('plaiu_scope', sa.Float()))

def downgrade():
    for t in TABLES:
        op.drop_column(t, 'plaiu_scope')
