"""range_violations table

Revision ID: 0056_range_violations
Revises: 0054_light_group_1_7_0
Create Date: 2026-10-25

Persiste les violations de plage sentinelles (ValueError('range') dans
decoder.py:read()) dans une table dédiée au lieu du compteur in-process
`RANGE_VIOLATIONS: dict`. Permet un suivi inter-session et une analyse
historique par capture / par field.
"""
from alembic import op

revision = '0056_range_violations'
down_revision = '0054_light_group_1_7_0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
        CREATE TABLE IF NOT EXISTS range_violations (
            id BIGSERIAL PRIMARY KEY,
            project_id VARCHAR NOT NULL,
            capture_id VARCHAR NOT NULL,
            decoder_version TEXT NOT NULL,
            field_code TEXT NOT NULL,
            n BIGINT NOT NULL,
            run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_range_violations_run_at ON range_violations(run_at DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_range_violations_capture ON range_violations(project_id, capture_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_range_violations_field ON range_violations(field_code)')


def downgrade():
    op.execute('DROP TABLE IF EXISTS range_violations')
