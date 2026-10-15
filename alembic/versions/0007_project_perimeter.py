"""projects.perimeter (B2 — jointure cell_ref)

Revision ID: 0007_project_perimeter
Revises: 0006_cell_ref_arcep_zone
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "0007_project_perimeter"
down_revision = "0006_cell_ref_arcep_zone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON nullable : vide tant qu'aucune cellule Orange n'a été jointe
    # à `cell_ref`. Pas d'index — on lit colonne entière à l'affichage.
    op.add_column(
        "projects",
        sa.Column("perimeter", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "perimeter")
