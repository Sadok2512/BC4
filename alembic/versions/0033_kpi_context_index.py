"""Cover exact-sequence analytic attribution without reading raw payload pages."""
from alembic import op

revision = '0033_kpi_context_index'
down_revision = '0032_nmf_ci_pairing'
branch_labels = depends_on = None


def upgrade():
    op.create_index('ix_stg_event_raw_context', 'stg_event_raw',
                    ['project_id', 'capture_id', 'seq'],
                    postgresql_include=['nmf_file_id', 'system'])


def downgrade():
    op.drop_index('ix_stg_event_raw_context', table_name='stg_event_raw')
