"""Capture-local signaling procedures."""
from alembic import op
revision = '0036_signaling_procedure'
down_revision = '0035_nmf_decoder_1_1_0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE signaling_procedure (
      id varchar(24) PRIMARY KEY, project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      capture_id varchar NOT NULL, type text NOT NULL CHECK(type IN
      ('rrc_setup','ho','call','data_session','attach','bearer','reestablishment')),
      technology text, seq_start integer NOT NULL, seq_end integer,
      duration_ms double precision CHECK(duration_ms>=0),
      outcome text NOT NULL CHECK(outcome IN ('ok','fail','incomplete')),cause text,
      boundary_seqs integer[] NOT NULL,
      CHECK(seq_end IS NULL OR seq_end>=seq_start))''')
    op.execute('CREATE INDEX signaling_procedure_capture ON signaling_procedure(project_id,capture_id,seq_start)')


def downgrade():
    op.drop_table('signaling_procedure')
