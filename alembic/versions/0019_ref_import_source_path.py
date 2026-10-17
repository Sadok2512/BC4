"""0.47.1 — reference_import.source_path (persistance du blob upload)

Jusqu'à 0.47.0, ``POST /settings/cell-ref/upload`` ne gardait AUCUNE
copie du blob uploadé — seul le sha256 était persisté. Conséquence :
impossible de rejouer un import ou d'auditer la source d'un référentiel.

Cette migration ajoute ``reference_import.source_path NVARCHAR NULL`` :
chemin absolu sur le volume ``/var/lib/bc4/references/<id>.csv`` où le
blob est écrit par la route. ``NULL`` = ancien import (pré-0.47.1,
source perdue).

Discipline additive stricte : aucune colonne existante modifiée. Pas
de backfill (impossible — la source n'était pas conservée pour les
anciens imports).

Revision ID: 0019_ref_import_source_path
Revises: 0018_project_populate_tracking
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019_ref_import_source_path"
down_revision: str = "0018_project_populate_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reference_import") as batch:
        batch.add_column(sa.Column("source_path", sa.String(), nullable=True))
    # 0.47.1 — Purge du seed démo trompeur ``geo-v1`` /
    # ``referentiel_zones_v1.csv`` / ``rows=0`` / ``demo.ingenieur``.
    # Il n'y a jamais eu de fichier derrière cette entrée — c'était un
    # mock UI qui a induit un agent en erreur (demande de fichier
    # inexistant). On ne purge QUE si le trio exact matche, pour ne
    # jamais toucher un éventuel upload réel du même nom.
    op.execute(
        """
        DELETE FROM geo_references
        WHERE id = 'geo-v1'
          AND filename = 'referentiel_zones_v1.csv'
          AND author = 'demo.ingenieur'
          AND rows = 0
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("reference_import") as batch:
        batch.drop_column("source_path")
    # Pas de rollback de la purge du seed (il reste supprimé — pas
    # d'invention de données en downgrade).
