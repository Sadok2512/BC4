"""Task runs, samples and server-side analytical evidence (BC1)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0026_task_run'
down_revision = '0025_dict_categories_v22'
branch_labels = depends_on = None

def upgrade():
    # Privacy first, in the same migration transaction; no unmasked backup is made.
    from app.services.task_privacy import migrate_existing_commands
    counts=migrate_existing_commands(op.get_bind())
    import logging
    logging.getLogger('alembic.runtime.migration').info('Command privacy redactions by project: %s', counts)
    op.create_table('task_run',
        sa.Column('id',sa.String(),primary_key=True),
        sa.Column('project_id',sa.String(),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('capture_id',sa.String(),nullable=False),
        *[sa.Column(n,sa.Integer(),nullable=n not in ('seq_start','seq_end')) for n in ('seq_start','seq_end','seq_daa','seq_dcomp')],
        *[sa.Column(n,sa.String()) for n in ('task_type','host','operator','band','tech','status','reason')],
        sa.Column('threads',sa.Integer()),
        *[sa.Column(n,sa.Float()) for n in ('max_duration_s','call_duration_s','duration_s','mos_aqdl')],
        sa.Column('bytes_dcomp',sa.BigInteger()),
        sa.UniqueConstraint('project_id','capture_id','seq_start'),
        sa.CheckConstraint("status IN ('ok','incomplete')"),
        sa.CheckConstraint("task_type IN ('HTTP_DL','HTTP_UL','VOICE','PING','OTHER')"),
        sa.CheckConstraint("status <> 'ok' OR seq_daa IS NOT NULL"))
    op.create_index('ix_task_run_project_capture','task_run',['project_id','capture_id'])
    op.create_table('task_sample',
        sa.Column('id',sa.String(),primary_key=True),
        sa.Column('task_id',sa.String(),sa.ForeignKey('task_run.id',ondelete='CASCADE'),nullable=False),
        sa.Column('seq',sa.Integer(),nullable=False),
        *[sa.Column(n,sa.Float()) for n in ('t_rel_s','bps','rsrp','rsrq','sinr','cqi')],
        sa.Column('bytes_cum',sa.BigInteger()),
        *[sa.Column(n,sa.Integer()) for n in ('pci','earfcn','mp_seq')],
        sa.Column('rat',sa.String()),
        sa.UniqueConstraint('task_id','seq'))
    op.create_index('ix_task_sample_task_seq','task_sample',['task_id','seq'])
    op.create_table('task_result',sa.Column('id',sa.String(),primary_key=True),
        sa.Column('project_id',sa.String(),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('sql',sa.Text(),nullable=False),sa.Column('filters',JSONB(),nullable=False),
        sa.Column('population',JSONB(),nullable=False),sa.Column('version',sa.String(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()))

def downgrade():
    op.drop_table('task_result');op.drop_table('task_sample');op.drop_table('task_run')
