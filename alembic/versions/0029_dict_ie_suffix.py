"""BC1 approved IE suffix categories and identifier flags. Data migration only."""
from alembic import op
from app.dict.migrate_v23 import upgrade_data, downgrade_data
revision = "0029_dict_ie_suffix"
down_revision = "0028_task_cellmeas"
branch_labels = depends_on = None


def upgrade():
    upgrade_data(op.get_bind())


def downgrade():
    downgrade_data(op.get_bind())
