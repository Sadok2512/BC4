"""Materialized network-configuration catalogue.

Revision ID: 0071_dict_network_catalog
Revises: 0070_signaling_materialized
"""
from alembic import op


revision = "0071_dict_network_catalog"
down_revision = "0070_signaling_materialized"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE dict_network_catalog_state (
      project_id varchar NOT NULL PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
      generation text NOT NULL,
      source_occurrences bigint NOT NULL,
      eligible_occurrences bigint NOT NULL,
      summary_rows bigint NOT NULL,
      total_occurrences bigint NOT NULL,
      distinct_param_keys bigint NOT NULL,
      available_messages varchar[] NOT NULL,
      catalog_rows bigint NOT NULL,
      group_by_options jsonb NOT NULL,
      built_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""CREATE TABLE dict_network_catalog_entry (
      project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      generation text NOT NULL,
      row_no bigint NOT NULL,
      system varchar NOT NULL,
      message varchar NOT NULL,
      normalized_path text NOT NULL,
      param_key text NOT NULL,
      display_name varchar,
      unit_converted varchar,
      choice_of varchar,
      discriminators jsonb NOT NULL,
      n bigint NOT NULL,
      captures varchar[] NOT NULL,
      PRIMARY KEY (project_id, generation, row_no)
    )""")
    op.execute("""CREATE TABLE dict_catalog_group_entry (
      project_id varchar NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      generation text NOT NULL,
      row_no bigint NOT NULL,
      system varchar NOT NULL,
      origin varchar,
      message varchar NOT NULL,
      functional_group varchar,
      param_key text NOT NULL,
      display_name varchar,
      choice_of varchar,
      discriminators jsonb,
      unit_converted varchar,
      is_identifier boolean NOT NULL,
      n bigint NOT NULL,
      PRIMARY KEY (project_id, generation, row_no)
    )""")
    with op.get_context().autocommit_block():
        op.execute("""CREATE INDEX CONCURRENTLY ix_dict_network_catalog_read
          ON dict_network_catalog_entry
          (project_id, generation, system, message, normalized_path, param_key)
          INCLUDE (display_name, unit_converted, choice_of, discriminators, n, captures)""")
        op.execute("""CREATE INDEX CONCURRENTLY ix_dict_catalog_group_read
          ON dict_catalog_group_entry
          (project_id, generation, system, origin, message, functional_group, param_key)
          INCLUDE (display_name, choice_of, discriminators, unit_converted, is_identifier, n)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_dict_catalog_group_read")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_dict_network_catalog_read")
    op.execute("DROP TABLE IF EXISTS dict_catalog_group_entry")
    op.execute("DROP TABLE IF EXISTS dict_network_catalog_entry")
    op.execute("DROP TABLE IF EXISTS dict_network_catalog_state")
