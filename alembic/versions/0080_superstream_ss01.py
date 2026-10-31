"""Harden Superstream project scope and optimistic concurrency.

Revision ID: 0080_superstream_ss01
Revises: 0079_probable_cell_links

The migration changes Superstream metadata only. It never reads or writes NMF
event/measurement data. Invalid pre-existing cross-project membership makes
the migration fail before DDL instead of being silently repaired.
"""

from alembic import op
import sqlalchemy as sa


revision = "0080_superstream_ss01"
down_revision = "0079_probable_cell_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM superstream_member m
            JOIN superstream s ON s.id = m.superstream_id
            WHERE m.project_id <> s.project_id
          ) THEN
            RAISE EXCEPTION
              'SS-01 refuses cross-project superstream_member rows';
          END IF;
        END $$
    """)

    op.add_column(
        "superstream",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_superstream_revision_positive", "superstream", "revision >= 1"
    )
    op.create_unique_constraint(
        "uq_superstream_id_project", "superstream", ["id", "project_id"]
    )
    op.create_check_constraint(
        "ck_superstream_member_position_nonnegative",
        "superstream_member",
        "position >= 0",
    )
    op.create_foreign_key(
        "fk_superstream_member_superstream_project",
        "superstream_member",
        "superstream",
        ["superstream_id", "project_id"],
        ["id", "project_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_superstream_member_superstream_project",
        "superstream_member",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_superstream_member_position_nonnegative",
        "superstream_member",
        type_="check",
    )
    op.drop_constraint(
        "uq_superstream_id_project", "superstream", type_="unique"
    )
    op.drop_constraint(
        "ck_superstream_revision_positive", "superstream", type_="check"
    )
    op.drop_column("superstream", "revision")
