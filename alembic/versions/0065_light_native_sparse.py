"""Sparse native storage for Light-only captures.

Revision ID: bc1_light_native_sparse
Revises: bc1_import_measurement_lookup

Deep captures keep nmf_event_deep as their sole typed event source.  Light
captures use this narrow, one-row-per-source-record representation; JSONB
objects contain non-null decoded fields only, avoiding the null bitmap and
fixed schema cost of the historical wide Light table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "bc1_light_native_sparse"
down_revision = "bc1_import_measurement_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nmf_event_light_native",
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_code", sa.String(length=24), nullable=False),
        sa.Column("system", sa.SmallInteger(), nullable=True),
        sa.Column("t_rel_s", sa.Float(), nullable=True),
        sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason_mask", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason_extra", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("unknown_cols", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("context_id", sa.BigInteger(), nullable=True),
        sa.Column("context_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("groups", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("x_2154", sa.Float(), nullable=True),
        sa.Column("y_2154", sa.Float(), nullable=True),
        sa.Column("position_source", sa.String(length=12), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "capture_id", "seq", name="pk_nmf_event_light_native"),
        sa.CheckConstraint(
            "(x_2154 IS NULL AND y_2154 IS NULL AND position_source IS NULL) OR "
            "(x_2154 IS NOT NULL AND y_2154 IS NOT NULL AND position_source='measured')",
            name="ck_light_native_position_proof",
        ),
    )
    op.create_index(
        "ix_light_native_project_event_capture_seq",
        "nmf_event_light_native",
        ["project_id", "event_code", "capture_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_light_native_project_event_capture_seq", table_name="nmf_event_light_native")
    op.drop_table("nmf_event_light_native")
