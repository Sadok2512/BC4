"""Documented LOCK attributes in typed repeated groups."""
from alembic import op
revision='0039_decoder_lock_fields'
down_revision='0038_decoder_cell_context'
branch_labels=depends_on=None


def upgrade():
    for table in ('nmf_event_deep','nmf_event_light'):
        op.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lock_forcings bigint')
    for table in ('nmf_event_group','nmf_event_light_group','nmf_event_light'):
        for name in ('type','params','system','band','channel','pci','barring','ho_band','ho_channel','ho_pci'):
            op.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lock_{name} bigint')


def downgrade():
    pass  # Never discard retained measurements on decoder downgrade.
