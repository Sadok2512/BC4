"""Persistent background NMF import queue."""
from alembic import op
import sqlalchemy as sa
revision = '0023_nmf_import_jobs'
down_revision = '0022_mp_ecgi_source'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('nmf_import_jobs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('report', sa.JSON(), nullable=True))
    op.create_index('ix_nmf_import_jobs_project_id', 'nmf_import_jobs', ['project_id'])


def downgrade():
    op.drop_table('nmf_import_jobs')
