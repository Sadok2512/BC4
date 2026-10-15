"""param_occurrence (0.12.0 — dictionnaire complet RRC LTE+NR)

Revision ID: 0008_param_occurrence
Revises: 0007_project_perimeter
Create Date: 2026-10-15

Table d'occurrences de paramètres RRC décodés via pycrate à partir de
`stg_event.payload_hex`. Scope strict `project_id`. L'ordre canonique
`(capture_id, seq)` est préservé via `stg_event_id` (FK vers l'event
source). La deny-list identités d'abonnés est appliquée AU
POPULATE : jamais une ligne qui matche DENY n'arrive ici.
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_param_occurrence"
down_revision = "0007_project_perimeter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_occurrence",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stg_event_id",
            sa.BigInteger(),
            sa.ForeignKey("stg_event.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("system", sa.String(), nullable=False),  # LTE | NR
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_converted", sa.Text(), nullable=True),
        sa.Column("unit_converted", sa.String(), nullable=True),
        sa.Column("operator", sa.String(), nullable=True),
        sa.Column("band", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
    )
    # Index requis par la mission.
    op.create_index(
        "ix_param_occ_sys_msg_path",
        "param_occurrence",
        ["project_id", "system", "message", "path"],
    )
    op.create_index(
        "ix_param_occ_op_band",
        "param_occurrence",
        ["project_id", "operator", "band"],
    )
    op.create_index(
        "ix_param_occ_path",
        "param_occurrence",
        ["project_id", "path"],
    )
    # Idempotence du populate : rejouer un populate pour le même event et
    # le même path n'ajoute pas de doublon (ON CONFLICT DO NOTHING au
    # moment de l'insert, voir app/dict/populate.py).
    op.create_unique_constraint(
        "uq_param_occ_event_path",
        "param_occurrence",
        ["project_id", "stg_event_id", "path"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_param_occ_event_path", "param_occurrence", type_="unique")
    op.drop_index("ix_param_occ_path", table_name="param_occurrence")
    op.drop_index("ix_param_occ_op_band", table_name="param_occurrence")
    op.drop_index("ix_param_occ_sys_msg_path", table_name="param_occurrence")
    op.drop_table("param_occurrence")
