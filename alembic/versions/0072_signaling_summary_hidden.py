"""Align Signaling summary with its materialized RF view.

Revision ID: 0072_signaling_summary_hidden
Revises: 0071_dict_network_catalog
"""
from alembic import op

revision = "0072_signaling_summary_hidden"
down_revision = "0071_dict_network_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE signaling_materialized_capture
      ADD COLUMN hidden jsonb NOT NULL DEFAULT '{}'::jsonb""")
    op.execute("""WITH rf AS (
      SELECT s.project_id,s.capture_id,count(e.*) AS rf_total
      FROM signaling_materialized_capture s
      LEFT JOIN signaling_materialized_event e
        ON e.project_id=s.project_id AND e.capture_id=s.capture_id
       AND e.generation=s.generation AND e.view='rf'
      GROUP BY s.project_id,s.capture_id
    ), outside AS (
      SELECT s.project_id,s.capture_id,count(e.*) AS without_rf_lane
      FROM signaling_materialized_capture s
      LEFT JOIN stg_event e
        ON e.project_id=s.project_id AND e.capture_id=s.capture_id
       AND e.event_code IN ('RRCSM','L3SM')
       AND e.system NOT IN ('LTE','NR')
      GROUP BY s.project_id,s.capture_id
    )
    UPDATE signaling_materialized_capture s SET
      hidden=jsonb_strip_nulls(jsonb_build_object(
        'without_rf_lane',NULLIF(LEAST(o.without_rf_lane,
          GREATEST(s.total-r.rf_total,0)),0),
        'procedure_projection_delta',NULLIF(GREATEST(
          s.total-r.rf_total-o.without_rf_lane,0),0))),
      total=r.rf_total
    FROM rf r,outside o
    WHERE r.project_id=s.project_id AND r.capture_id=s.capture_id
      AND o.project_id=s.project_id AND o.capture_id=s.capture_id""")
    op.execute("ALTER TABLE signaling_materialized_capture ALTER COLUMN hidden DROP DEFAULT")


def downgrade() -> None:
    op.execute("""UPDATE signaling_materialized_capture s SET total=(
      SELECT COALESCE(sum(value::bigint),0)
      FROM jsonb_each_text(s.event_counts))""")
    op.execute("ALTER TABLE signaling_materialized_capture DROP COLUMN hidden")
