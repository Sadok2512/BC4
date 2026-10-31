"""Materialize probable serving, neighbour and NR-anchor map links.

Revision ID: 0079_probable_cell_links
Revises: 0078_cell_identity_strength
"""
from alembic import op


revision = "0079_probable_cell_links"
down_revision = "0078_cell_identity_strength"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE nmf_probable_cell_link (
      project_id varchar NOT NULL,
      capture_id varchar NOT NULL,
      seq integer NOT NULL,
      reference_version varchar NOT NULL,
      link_payload jsonb NOT NULL,
      built_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id,capture_id)
        REFERENCES nmf_capture(project_id,capture_id) ON DELETE CASCADE
    )""")
    op.execute("""CREATE TABLE nmf_probable_cell_link_state (
      project_id varchar NOT NULL,
      capture_id varchar NOT NULL,
      reference_version varchar NOT NULL,
      built_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id,capture_id)
        REFERENCES nmf_capture(project_id,capture_id) ON DELETE CASCADE
    )""")
    with op.get_context().autocommit_block():
        op.execute("""CREATE UNIQUE INDEX CONCURRENTLY
          ux_nmf_probable_cell_link_seq ON nmf_probable_cell_link
          (project_id,capture_id,seq)""")
        op.execute("""CREATE UNIQUE INDEX CONCURRENTLY
          ux_nmf_probable_cell_link_state ON nmf_probable_cell_link_state
          (project_id,capture_id)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_nmf_probable_cell_link_state")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_nmf_probable_cell_link_seq")
    op.execute("DROP TABLE nmf_probable_cell_link_state")
    op.execute("DROP TABLE nmf_probable_cell_link")
