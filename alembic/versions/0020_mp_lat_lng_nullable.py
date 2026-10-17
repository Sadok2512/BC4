"""0.47.3 — measurement_points.lat/lng nullable + geo_source

Règle « jamais une mesure jetée » : une mesure radio/data sans fix GPS
reste conservée en base, mais avec ``lat IS NULL AND lng IS NULL``
plutôt que ``0,0`` inventé ou qu'un skip pur et simple.

- ``lat`` / ``lng`` passent de ``NOT NULL`` à ``NULL`` autorisé. Les
  valeurs ``0,0`` ne sont JAMAIS écrites — c'était la règle historique
  (pas de position inventée) ; elle reste. Simplement, la mesure
  elle-même n'est plus perdue : elle sort des cartes et de la voie géo
  « position », pas des KPI radio.
- Nouvelle colonne ``geo_source`` NVARCHAR NULL :
    * ``NULL``                   : pas de GPS pour cette mesure (indoor,
      perte de fix). La mesure compte dans les KPI radio/data mais le
      chip « Géo » la compte en ``none``.
    * ``'gps_fix'``              : GPS fix récupéré du dernier GPS
      event (comportement historique quand lat/lng non-NULL).
    * ``'ecgi_cell_centroid'``   : (futur) propagé depuis cell_ref si
      ECGI strict et pas de GPS natif.

Discipline additive stricte : les anciennes lignes (toutes NOT NULL)
restent valides ; aucun backfill nécessaire. La migration ne change pas
la valeur par défaut (``geo_source`` NULL = « inconnu », distinct de
``none``).

Revision ID: 0020_mp_lat_lng_nullable
Revises: 0019_ref_import_source_path
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020_mp_lat_lng_nullable"
down_revision: str = "0019_ref_import_source_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("measurement_points") as batch:
        batch.alter_column("lat", nullable=True)
        batch.alter_column("lng", nullable=True)
        batch.add_column(sa.Column("geo_source", sa.String(), nullable=True))
    # Backfill geo_source pour les lignes existantes (toutes ont lat/lng
    # NOT NULL par contrainte historique) → 'gps_fix'. Les nouvelles
    # mesures sans GPS auront geo_source=NULL (le fix populate.py arrive
    # en même temps que cette migration).
    op.execute(
        "UPDATE measurement_points SET geo_source = 'gps_fix' "
        "WHERE geo_source IS NULL AND lat IS NOT NULL AND lng IS NOT NULL"
    )


def downgrade() -> None:
    # Downgrade impossible proprement si des mesures sans GPS existent
    # déjà (NOT NULL échouerait). On ne touche pas la nullability.
    with op.batch_alter_table("measurement_points") as batch:
        batch.drop_column("geo_source")
