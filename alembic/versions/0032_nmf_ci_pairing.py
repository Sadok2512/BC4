"""Keep the source sequence of CI-derived task SINR independently of CELLMEAS."""
from alembic import op
import sqlalchemy as sa
revision='0032_nmf_ci_pairing'
down_revision='0031_nmf_decoder'
branch_labels=depends_on=None

def upgrade():
    op.add_column('task_sample',sa.Column('sinr_seq',sa.Integer()))
    op.add_column('task_sample',sa.Column('sinr_seq_gap',sa.Integer()))

def downgrade():
    op.drop_column('task_sample','sinr_seq_gap')
    op.drop_column('task_sample','sinr_seq')
