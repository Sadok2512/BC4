"""KPI integral quality and explicit capture-local radio distance."""
from alembic import op
import sqlalchemy as sa
revision='0027_task_pairing'
down_revision='0026_task_run'
branch_labels=depends_on=None

def upgrade():
    op.drop_constraint('task_run_status_check','task_run',type_='check')
    op.create_check_constraint('task_run_status_check','task_run',"status IN ('ok','incomplete','partial')")
    op.add_column('task_sample',sa.Column('seq_gap',sa.Integer()))
    op.add_column('task_sample',sa.Column('capture_time_s',sa.Float()))
    from app.services.task_run import populate_tasks
    from sqlalchemy.orm import Session
    db=Session(bind=op.get_bind())
    for pid in db.execute(sa.text('SELECT DISTINCT project_id FROM task_run')).scalars().all():
        populate_tasks(db,pid)

def downgrade():
    op.execute("UPDATE task_run SET status='incomplete' WHERE status='partial'")
    op.drop_column('task_sample','capture_time_s')
    op.drop_column('task_sample','seq_gap')
    op.drop_constraint('task_run_status_check','task_run',type_='check')
    op.create_check_constraint('task_run_status_check','task_run',"status IN ('ok','incomplete')")
