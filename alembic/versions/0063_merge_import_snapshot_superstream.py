"""Merge import snapshot and superstream migration branches.

Revision ID: 0063_merge_import_superstream
Revises: 0061_import_job_parsing_snapshot, 0062_superstream
"""

revision = "0063_merge_import_superstream"
down_revision = ("0061_import_job_parsing_snapshot", "0062_superstream")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
