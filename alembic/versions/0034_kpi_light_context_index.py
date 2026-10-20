"""Cover source event ranges used to validate filtered Light buckets."""
from alembic import op
revision = '0034_kpi_light_context_index'
down_revision = '0033_kpi_context_index'
branch_labels = depends_on = None


def upgrade():
    op.create_index('ix_stg_event_raw_context_event', 'stg_event_raw',
                    ['project_id', 'capture_id', 'event_code', 'seq'],
                    postgresql_include=['nmf_file_id', 'system'])


def downgrade():
    op.drop_index('ix_stg_event_raw_context_event', table_name='stg_event_raw')
