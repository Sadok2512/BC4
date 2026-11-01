"""Extend signaling procedures with certified evidence fields.

Revision ID: 0082_procedure_evidence
Revises: 0081_workspace_templates
"""

from alembic import op


revision = "0083_procedure_evidence"
down_revision = "0082_metrics_catalog_cache_scope"
branch_labels = None
depends_on = None


_TYPES = (
    "rrc_setup", "rrc_connection", "ho", "call", "data_session", "attach", "bearer", "reestablishment",
    "lte_rrc_setup", "nr_rrc_setup", "rrc_setup_unknown_rat",
    "lte_rrc_reestablishment", "nr_rrc_reestablishment", "rrc_reestablishment_unknown_rat",
    "lte_rlf_probable", "nr_rlf_probable", "lte_nas_attach", "nr_registration", "lte_rach",
    "lte_ho_intra_frequency", "lte_ho_inter_frequency", "lte_ho_unknown_frequency",
    "lte_eps_bearer_setup", "ims_registration", "volte_call_setup", "vonr_call_setup",
    "voice_call_setup_unknown_rat", "endc_scg_failure",
)


def upgrade() -> None:
    op.execute("ALTER TABLE signaling_procedure ALTER COLUMN id TYPE varchar(64)")
    op.execute("ALTER TABLE signaling_procedure DROP CONSTRAINT IF EXISTS signaling_procedure_type_check")
    allowed = ",".join("'%s'" % value for value in _TYPES)
    op.execute(f"ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_type_check CHECK(type IN ({allowed}))")
    op.execute("""ALTER TABLE signaling_procedure
      ADD COLUMN ue_key text,
      ADD COLUMN session_key text,
      ADD COLUMN start_time text,
      ADD COLUMN end_time text,
      ADD COLUMN source_pci integer,
      ADD COLUMN source_arfcn integer,
      ADD COLUMN target_pci integer,
      ADD COLUMN target_arfcn integer,
      ADD COLUMN bearer_id integer,
      ADD COLUMN ebi integer,
      ADD COLUMN qci integer,
      ADD COLUMN qfi integer,
      ADD COLUMN five_qi integer,
      ADD COLUMN s_nssai text,
      ADD COLUMN result text,
      ADD COLUMN failure_cause text,
      ADD COLUMN evidence_level text,
      ADD COLUMN source_event_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
      ADD COLUMN latitude double precision,
      ADD COLUMN longitude double precision,
      ADD COLUMN gps_seq integer,
      ADD COLUMN engine_version text""")
    op.execute("ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_result_check CHECK(result IS NULL OR result IN ('ATTEMPT','SUCCESS','FAILURE','ABNORMAL_RELEASE','DROP','TIMEOUT','UNKNOWN'))")
    op.execute("ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_evidence_check CHECK(evidence_level IS NULL OR evidence_level IN ('PROVEN','PROBABLE','UNKNOWN'))")
    op.execute("CREATE INDEX ix_signaling_procedure_scope_result ON signaling_procedure(project_id,capture_id,type,result,evidence_level,seq_start)")


def downgrade() -> None:
    op.execute("DELETE FROM signaling_procedure WHERE engine_version LIKE 'procedure-v1|%'")
    op.execute("DROP INDEX IF EXISTS ix_signaling_procedure_scope_result")
    op.execute("ALTER TABLE signaling_procedure DROP CONSTRAINT IF EXISTS signaling_procedure_result_check")
    op.execute("ALTER TABLE signaling_procedure DROP CONSTRAINT IF EXISTS signaling_procedure_evidence_check")
    for column in (
        "engine_version", "gps_seq", "longitude", "latitude", "source_event_ids", "evidence_level",
        "failure_cause", "result", "s_nssai", "five_qi", "qfi", "qci", "ebi", "bearer_id",
        "target_arfcn", "target_pci", "source_arfcn", "source_pci", "end_time", "start_time",
        "session_key", "ue_key",
    ):
        op.execute(f"ALTER TABLE signaling_procedure DROP COLUMN {column}")
    op.execute("ALTER TABLE signaling_procedure DROP CONSTRAINT IF EXISTS signaling_procedure_type_check")
    op.execute("""ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_type_check
      CHECK(type IN ('rrc_setup','rrc_connection','ho','call','data_session','attach','bearer','reestablishment'))""")
    op.execute("ALTER TABLE signaling_procedure ALTER COLUMN id TYPE varchar(24)")
