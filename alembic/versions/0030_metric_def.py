"""Proof-gated Nemo metric definitions and measured observations.

No reference rows seeded: the requested Nemo format is not yet supplied.
field_index is the zero-based CSV token index (event=0, timestamp=1),
matching staging cN. proof_ref must cite the document page and printed field.
"""
from alembic import op
revision='0030_metric_def'
down_revision='0029_dict_ie_suffix'
branch_labels=depends_on=None

def upgrade():
    op.execute('''CREATE TABLE metric_def (
      code text PRIMARY KEY CHECK (code ~ '^[a-z][a-z0-9_]*$'),
      event_code text NOT NULL,
      field_index integer NOT NULL CHECK (field_index >= 4),
      unit text NOT NULL CHECK (length(trim(unit))>0),
      scale numeric NOT NULL CHECK (scale <> 0),
      tech text NOT NULL CHECK (tech IN ('LTE','NR','BOTH')),
      label text NOT NULL,
      proof_ref text NOT NULL CHECK (length(trim(proof_ref))>0)
    )''')
    op.execute('''CREATE TABLE metric_sample (
      project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      capture_id varchar NOT NULL,
      seq integer NOT NULL,
      metric_code text NOT NULL REFERENCES metric_def(code),
      raw_event_id bigint NOT NULL REFERENCES stg_event_raw(id) ON DELETE CASCADE,
      raw_value text NOT NULL,
      value double precision NOT NULL,
      PRIMARY KEY(project_id,capture_id,seq,metric_code)
    )''')

def downgrade():
    op.drop_table('metric_sample')
    op.drop_table('metric_def')
