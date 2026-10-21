"""Nemo explicit contexts, documented event attributes and CA projections."""
from alembic import op

revision='0038_decoder_cell_context'
down_revision='0037_sig_rrc_connection'
branch_labels=depends_on=None


def upgrade():
    for table in ('nmf_event_deep','nmf_event_light'):
        op.execute(f'ALTER TABLE {table} ADD COLUMN context_id bigint, ADD COLUMN context_ids bigint[]')
        for code in ('sei_mcc','sei_mnc','sei_mme_group','sei_mme_code','cad_volte_cause'):
            op.execute(f'ALTER TABLE {table} ADD COLUMN {code} bigint')
    op.execute('''CREATE TABLE nmf_cell_second (
      project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      capture_id varchar NOT NULL, second bigint NOT NULL, event_code text NOT NULL,
      metric_code text NOT NULL, cell_index integer NOT NULL,
      seq_first integer NOT NULL,seq_last integer NOT NULL,value double precision,
      weight double precision,reason text,decoder_version text NOT NULL,
      PRIMARY KEY(project_id,capture_id,second,event_code,metric_code,cell_index))''')
    op.execute('''CREATE TABLE nmf_event_pair (
      project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      capture_id varchar NOT NULL,type text NOT NULL,context_id bigint,
      seq_start integer NOT NULL,seq_end integer,seq_hoi integer,
      duration_nemo_ms double precision,ho_duration_nemo_ms double precision,
      ho_duration_hoi_ms double precision,outcome text NOT NULL,cause text,
      decoder_version text NOT NULL,
      PRIMARY KEY(project_id,capture_id,type,seq_start))''')
    # Irreversible privacy cleanup: redact only proven private fields, never delete events.
    for table in ('nmf_event_deep','nmf_event_light'):
        op.execute(f'''UPDATE {table} SET caa_phone_number=NULL,caa_own_phone_number=NULL
          WHERE event_code='CAA' AND (caa_phone_number IS NOT NULL OR caa_own_phone_number IS NOT NULL)''')
    op.execute('''UPDATE nmf_event_deep d SET tokens=ARRAY(
      SELECT CASE WHEN (d.event_code='CAA' AND (coalesce(d.tokens[3],'')<>'1' AND n>=4 OR n IN (8,9)))
        OR (d.event_code='SEI' AND (coalesce(d.tokens[3],'') NOT IN ('','0') AND n>=4 OR n IN (6,9,10,13)))
        THEN '' ELSE v END FROM unnest(d.tokens) WITH ORDINALITY AS u(v,n) ORDER BY n)
      WHERE event_code IN ('CAA','SEI')''')
    op.execute('''UPDATE stg_event_raw d SET raw_fields=(
      SELECT jsonb_object_agg(key, CASE WHEN
        (d.event_code='CAA' AND key IN ('c7','c8')) OR
        (d.event_code='SEI' AND key IN ('c5','c8','c9','c12')) OR
        lower(regexp_replace(key,'[^a-zA-Z0-9]','','g')) IN
          ('phonenumber','ownphonenumber','lac','tmsi','ptmsi','mtmsi') OR
        (((d.event_code='CAA' AND coalesce(d.raw_fields->>'c2','')<>'1') OR
          (d.event_code='SEI' AND coalesce(d.raw_fields->>'c2','') NOT IN ('','0')))
          AND key ~ '^c([3-9]|[1-9][0-9]+)$')
        THEN 'null'::jsonb ELSE value END) FROM jsonb_each(d.raw_fields))
      WHERE event_code IN ('CAA','SEI')''')


def downgrade():
    # Data retention: downgrading the decoder cannot erase retained observations.
    pass
