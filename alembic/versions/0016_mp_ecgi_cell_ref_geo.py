"""ECGI sur measurement_points + commune/insee sur cell_ref (0.41.0)

Ajouts additifs stricts :

- ``measurement_points.ecgi`` (varchar, nullable, index) :
  identifiant cellule serving propagé depuis le dernier SIB1 de la
  capture, matché par ``(pci, earfcn)`` en ordre
  ``(capture_id, seq)`` (JAMAIS ``ts`` : ordre canonique Nemo). Après
  un handover sans SIB1 relu, la valeur reste **NULL** — jamais
  l'ancien ECGI inventé.
- ``cell_ref.commune`` + ``cell_ref.insee`` (varchar, nullable, index
  sur ``insee``) : enrichissement par upload opérateur du référentiel
  géo (0.41.0 — route ``POST /settings/cell-ref/upload``). ``dr``,
  ``plaque``, ``dor``, ``arcep_zone`` existent déjà depuis 0.14.0 /
  0.6.1 — pas de retypage.

Discipline :
- Aucune colonne existante n'est modifiée.
- Index ``ix_measurement_points_ecgi`` pour les jointures
  ``mp.ecgi → cell_ref.eci`` (filtres dr/plaque/dor/arcep).
- Downgrade propre.

Revision ID: 0016_mp_ecgi_cell_ref_geo
Revises: 0015_skill
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_mp_ecgi_cell_ref_geo"
down_revision = "0015_skill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("measurement_points") as batch:
        batch.add_column(sa.Column("ecgi", sa.String(), nullable=True))
    op.create_index(
        "ix_measurement_points_ecgi",
        "measurement_points",
        ["ecgi"],
    )

    with op.batch_alter_table("cell_ref") as batch:
        batch.add_column(sa.Column("commune", sa.String(), nullable=True))
        batch.add_column(sa.Column("insee",   sa.String(), nullable=True))
    op.create_index("ix_cell_ref_insee", "cell_ref", ["insee"])


def downgrade() -> None:
    op.drop_index("ix_cell_ref_insee", table_name="cell_ref")
    with op.batch_alter_table("cell_ref") as batch:
        batch.drop_column("insee")
        batch.drop_column("commune")

    op.drop_index("ix_measurement_points_ecgi", table_name="measurement_points")
    with op.batch_alter_table("measurement_points") as batch:
        batch.drop_column("ecgi")
