"""Decoder 1.10.3 — add macrate_scope + macrateu_scope columns for NR Scope.

NR MACRATE p.534 #1 and NR MACRATEU p.538 #1. LTE schemas have no Scope.
"""
from alembic import op
import sqlalchemy as sa

revision = '0087_macrate_nr_scope'
down_revision = '0086_plaiu_nr_scope'
branch_labels = None
depends_on = None

TABLES = ('nmf_event_light','nmf_event_deep','nmf_event_light_group','nmf_event_group')

def upgrade():
    for t in TABLES:
        op.add_column(t, sa.Column('macrate_scope', sa.Float()))
        op.add_column(t, sa.Column('macrateu_scope', sa.Float()))

def downgrade():
    for t in TABLES:
        op.drop_column(t, 'macrate_scope')
        op.drop_column(t, 'macrateu_scope')
