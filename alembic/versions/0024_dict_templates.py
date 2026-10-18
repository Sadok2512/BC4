"""RRC template configuration, no measurements or reference data.

Author: BC1. Follows the already applied NMF queue migration.
"""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0024_dict_templates'
down_revision = '0023_nmf_import_jobs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dict_category', sa.Column('id', sa.String(), primary_key=True), sa.Column('label', sa.String(), nullable=False), sa.Column('position', sa.Integer(), nullable=False, unique=True))
    op.create_table('dict_category_map', sa.Column('technology', sa.String(), primary_key=True), sa.Column('path_prefix', sa.String(), primary_key=True), sa.Column('category_id', sa.String(), sa.ForeignKey('dict_category.id'), nullable=False))
    op.create_table('dict_template', sa.Column('category_id', sa.String(), sa.ForeignKey('dict_category.id'), primary_key=True), sa.Column('entries', JSONB(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False, server_default='1'))
    data = json.loads((Path(__file__).resolve().parents[2] / 'app/dict/config/templates_v1.json').read_text())
    db = op.get_bind()
    for category in data['categories']:
        db.execute(sa.text('INSERT INTO dict_category(id,label,position) VALUES (:id,:label,:position)'),category)
        db.execute(sa.text('INSERT INTO dict_template(category_id,entries) VALUES (:id,CAST(:entries AS jsonb))'),{'id':category['id'],'entries':json.dumps(category['entries'])})
    for row in data['maps']:
        db.execute(sa.text('INSERT INTO dict_category_map(technology,path_prefix,category_id) VALUES (:technology,:path_prefix,:category_id)'),row)


def downgrade():
    op.drop_table('dict_template')
    op.drop_table('dict_category_map')
    op.drop_table('dict_category')
