"""cell_ref.arcep_zone (B1-réf — dimension Zone ARCEP)

Revision ID: 0006_cell_ref_arcep_zone
Revises: 0005_app_user
Create Date: 2026-10-15

Amendement B1-réf : ajoute la colonne `arcep_zone` à `cell_ref`,
alimentée par la colonne `cat_arcep_code` du CSV source. Les 11
catégories ARCEP réelles sont persistées LITTÉRALEMENT (pas de
normalisation, pas de ré-encodage). `"(null)"` littéral et chaîne
vide `""` → NULL en base. La dimension est **orthogonale** à la géo
(DOR/DR/Plaque) — pas de FK, pas de contrainte CHECK figée (les
libellés ARCEP peuvent évoluer indépendamment du code).

Index btree pour permettre un `GROUP BY arcep_zone` honnête sur
~460 k lignes dans `/reference/cell/summary`.
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_cell_ref_arcep_zone"
down_revision = "0005_app_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cell_ref",
        sa.Column("arcep_zone", sa.Text(), nullable=True),
    )
    op.create_index("ix_cell_ref_arcep_zone", "cell_ref", ["arcep_zone"])


def downgrade() -> None:
    op.drop_index("ix_cell_ref_arcep_zone", table_name="cell_ref")
    op.drop_column("cell_ref", "arcep_zone")
