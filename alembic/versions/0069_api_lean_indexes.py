"""Capture clock and dictionary catalogue covering indexes.

Revision ID: 0069_api_lean_indexes
Revises: 0068_pg_stat_statements
"""
from alembic import op

revision = "0069_api_lean_indexes"
down_revision = "0068_pg_stat_statements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_api_stg_event_raw_capture_seq ON stg_event_raw (project_id, capture_id, seq) INCLUDE (ts)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_api_stg_event_capture_seq ON stg_event (project_id, capture_id, seq) INCLUDE (ts)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_api_measurement_points_capture ON measurement_points (project_id, capture_id)")
        op.execute("""CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_api_param_occ_catalog_cover
          ON param_occurrence (project_id, system, origin, message, functional_group, param_key)
          INCLUDE (display_name, choice_of, discriminators, unit_converted, is_identifier)
          WHERE param_key IS NOT NULL AND COALESCE(is_identifier, false) = false""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in ("ix_api_param_occ_catalog_cover", "ix_api_measurement_points_capture",
                     "ix_api_stg_event_capture_seq", "ix_api_stg_event_raw_capture_seq"):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
