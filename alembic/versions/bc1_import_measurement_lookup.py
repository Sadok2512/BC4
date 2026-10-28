"""Index canonical measurement lookup used by sliced finalization.

Revision ID: bc1_import_measurement_lookup
Revises: 0063_merge_import_superstream

The numeric revision/file name is intentionally assigned by BC3 at merge.
"""
from alembic import op


revision = "bc1_import_measurement_lookup"
down_revision = "0063_merge_import_superstream"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_measurement_points_project_capture_seq",
        "measurement_points",
        ["project_id", "capture_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_points_project_capture_seq",
        table_name="measurement_points",
    )
