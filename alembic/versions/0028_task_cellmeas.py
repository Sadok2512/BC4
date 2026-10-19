"""Pair CELLMEAS independently from CQI, preserving explicit provenance."""
from alembic import op
import sqlalchemy as sa
revision='0028_task_cellmeas'
down_revision='0027_task_pairing'
branch_labels=depends_on=None

def upgrade():
    op.add_column('task_sample',sa.Column('cqi_seq',sa.Integer()))
    op.add_column('task_sample',sa.Column('cqi_seq_gap',sa.Integer()))
    from app.services.task_run import populate_tasks
    from sqlalchemy.orm import Session
    db=Session(bind=op.get_bind())
    for pid in db.execute(sa.text('SELECT DISTINCT project_id FROM task_run')).scalars().all():
        populate_tasks(db,pid)

def downgrade():
    op.drop_column('task_sample','cqi_seq_gap')
    op.drop_column('task_sample','cqi_seq')
