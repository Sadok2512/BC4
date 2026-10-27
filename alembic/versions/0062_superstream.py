"""Superstream : liste ordonnée de captures d'un même projet.

Revision ID: 0062_superstream
Revises: 0060_light_dci_count_repair

Contrat : un superstream groupe des captures d'un MÊME projet sans jamais
copier de données. Lecture dans l'ordre canonique (position, seq) ;
JAMAIS trié ou entrelacé par ts. Les membres sont des captures TERMINÉES
(filtre côté route ; le FK composite garantit la cohérence (pid, cap)).

Note rebase : 0061 est réservé à BC1 (patch antérieur). Si BC1 pose 0061
avant ce merge, BC3 rebase 0062 → 0063 (down_revision 0061). Pas de down
destructif prévu : downgrade droppe les deux tables, les superstreams
définis sont jetés.
"""

from alembic import op
import sqlalchemy as sa


revision = "0062_superstream"
down_revision = "0060_light_dci_count_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "superstream",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "name", name="uq_superstream_project_name"),
    )
    op.create_index(
        "ix_superstream_project_id",
        "superstream",
        ["project_id"],
    )

    op.create_table(
        "superstream_member",
        sa.Column(
            "superstream_id",
            sa.String(),
            sa.ForeignKey("superstream.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("capture_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("superstream_id", "position", name="pk_superstream_member"),
        sa.UniqueConstraint(
            "superstream_id",
            "capture_id",
            name="uq_superstream_member_capture",
        ),
        # FK composite vers nmf_capture(project_id, capture_id) : garantit par
        # construction qu'un membre pointe sur une capture existante du MÊME
        # projet. Le routeur applique en plus que project_id du membre ==
        # project_id du superstream (422 sinon) et que la capture est
        # terminée (status 'done' dans nmf_file).
        sa.ForeignKeyConstraint(
            ["project_id", "capture_id"],
            ["nmf_capture.project_id", "nmf_capture.capture_id"],
            name="fk_superstream_member_capture",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_superstream_member_capture",
        "superstream_member",
        ["project_id", "capture_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_superstream_member_capture", table_name="superstream_member")
    op.drop_table("superstream_member")
    op.drop_index("ix_superstream_project_id", table_name="superstream")
    op.drop_table("superstream")
