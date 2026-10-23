"""Use text storage for NMF documented string fields."""
from alembic import op
revision='0044_nmf_string_columns'
down_revision='0043_kind'
branch_labels=None
depends_on=None
COLS = []
def upgrade():
    bind = op.get_bind()
    view = bind.exec_driver_sql("SELECT pg_get_viewdef('nmf_metric_value'::regclass, true)").scalar()
    op.execute('DROP VIEW IF EXISTS nmf_metric_value')
    for table in ('nmf_event_deep','nmf_event_light'):
        for col in COLS:
            op.execute(f'ALTER TABLE {table} ALTER COLUMN {col} TYPE text USING {col}::text')
    if view:
        op.execute('CREATE VIEW nmf_metric_value AS ' + view)
def downgrade():
    pass
