"""Materialized Signaling events, points and capture summaries.

Revision ID: 0070_signaling_materialized
Revises: 0069_api_lean_indexes
"""
from alembic import op

revision = "0070_signaling_materialized"
down_revision = "0069_api_lean_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE signaling_materialized_capture (
      project_id text NOT NULL,
      capture_id text NOT NULL,
      generation text NOT NULL,
      decoder_version text NOT NULL,
      event_counts jsonb NOT NULL,
      tracks jsonb NOT NULL,
      total bigint NOT NULL,
      seq_start bigint,
      seq_end bigint,
      t_rel_start_s double precision NOT NULL DEFAULT 0,
      t_rel_end_s double precision,
      indoor boolean NOT NULL,
      built_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, capture_id),
      FOREIGN KEY (project_id, capture_id)
        REFERENCES nmf_capture(project_id, capture_id) ON DELETE CASCADE
    )""")
    op.execute("""CREATE TABLE signaling_materialized_event (
      project_id text NOT NULL,
      capture_id text NOT NULL,
      seq bigint NOT NULL,
      generation text NOT NULL,
      view text NOT NULL CHECK (view IN ('legacy','rf')),
      id text NOT NULL,
      seq_end bigint,
      t_rel_s double precision,
      t_rel_end_s double precision,
      lane text NOT NULL,
      type text NOT NULL,
      kind text NOT NULL,
      duration_ms double precision,
      outcome text,
      cause text,
      label text NOT NULL,
      attrs jsonb NOT NULL,
      pivot_seq bigint,
      linked_seqs bigint[] NOT NULL,
      link_rule text NOT NULL,
      seq_gap bigint,
      context_id bigint,
      session_id text,
      decoder_version text NOT NULL,
      PRIMARY KEY (project_id, capture_id, seq, generation, view, id),
      FOREIGN KEY (project_id, capture_id)
        REFERENCES nmf_capture(project_id, capture_id) ON DELETE CASCADE
    )""")
    op.execute("""CREATE TABLE signaling_materialized_point (
      project_id text NOT NULL,
      capture_id text NOT NULL,
      seq bigint NOT NULL,
      generation text NOT NULL,
      t_rel_s double precision,
      lat double precision,
      lng double precision,
      protocol text NOT NULL,
      layer text NOT NULL,
      gps_seq bigint,
      seq_gap bigint,
      technology text,
      direction text,
      message_name text NOT NULL,
      procedure_ids text[] NOT NULL,
      decoder_version text NOT NULL,
      PRIMARY KEY (project_id, capture_id, seq, generation),
      FOREIGN KEY (project_id, capture_id)
        REFERENCES nmf_capture(project_id, capture_id) ON DELETE CASCADE
    )""")
    with op.get_context().autocommit_block():
        op.execute("""CREATE INDEX CONCURRENTLY ix_signaling_event_window
          ON signaling_materialized_event
          (project_id, capture_id, generation, view, seq, id)""")
        op.execute("""CREATE INDEX CONCURRENTLY ix_signaling_event_time_window
          ON signaling_materialized_event
          (project_id, capture_id, generation, view, t_rel_s, seq)""")
        op.execute("""CREATE INDEX CONCURRENTLY ix_signaling_point_window
          ON signaling_materialized_point
          (project_id, capture_id, generation, seq)""")
        op.execute("""CREATE INDEX CONCURRENTLY ix_signaling_point_time_window
          ON signaling_materialized_point
          (project_id, capture_id, generation, t_rel_s, seq)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in (
            "ix_signaling_point_time_window", "ix_signaling_point_window",
            "ix_signaling_event_time_window", "ix_signaling_event_window",
        ):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute("DROP TABLE signaling_materialized_point")
    op.execute("DROP TABLE signaling_materialized_event")
    op.execute("DROP TABLE signaling_materialized_capture")
