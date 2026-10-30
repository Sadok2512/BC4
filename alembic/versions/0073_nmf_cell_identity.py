"""Stable physical identity for repeated CELLMEAS cells.

Revision ID: 0073_nmf_cell_identity
Revises: 0072_signaling_summary_hidden
"""
from alembic import op


revision = "0073_nmf_cell_identity"
down_revision = "0072_signaling_summary_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE nmf_cell_identity (
      project_id varchar NOT NULL,
      capture_id varchar NOT NULL,
      seq integer NOT NULL,
      event_code text NOT NULL,
      cell_index integer NOT NULL,
      system smallint NOT NULL,
      cell_type integer NOT NULL,
      cell_arfcn bigint,
      cell_pci integer,
      decoder_version text NOT NULL,
      built_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, capture_id, seq, event_code, cell_index),
      FOREIGN KEY (project_id, capture_id)
        REFERENCES nmf_capture(project_id, capture_id) ON DELETE CASCADE,
      CHECK ((cell_arfcn IS NULL) = (cell_pci IS NULL))
    )""")
    with op.get_context().autocommit_block():
        op.execute("""CREATE INDEX CONCURRENTLY ix_nmf_cell_identity_physical_seq
          ON nmf_cell_identity
          (project_id, capture_id, event_code, system, cell_type,
           cell_arfcn, cell_pci, seq)
          INCLUDE (cell_index, decoder_version)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_nmf_cell_identity_physical_seq")
    op.execute("DROP TABLE nmf_cell_identity")
