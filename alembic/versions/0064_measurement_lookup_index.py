"""Index canonical measurement lookup used by sliced finalization.

Revision ID: bc1_import_measurement_lookup
Revises: 0063_merge_import_superstream

Nommage de fichier `0064_measurement_lookup_index.py` attribué par BC3 au
merge (2026-10-28). Le `revision` ID textuel `bc1_import_measurement_lookup`
est conservé pour ne pas invalider l'historique Alembic déjà appliqué sur
une DB (prod ou éphémère) où `alembic_version.version_num` pointe sur
`bc1_import_measurement_lookup`.

L'index est posé en CONCURRENTLY pour ne pas bloquer les lectures et
écritures existantes sur `measurement_points` pendant la pose. Alembic
tourne par défaut DDL dans une transaction : CONCURRENTLY exige d'être
hors transaction, d'où `op.get_context().autocommit_block()` qui ferme
proprement la tx Alembic avant la commande, puis la rouvre après.

`if_not_exists=True` garantit l'idempotence d'un rejoue (ex. un
`alembic upgrade head` lancé sur une DB où l'index est déjà posé par
une version antérieure sans CONCURRENTLY — c'est le cas prod après le
premier déploiement 0.93.0 où l'index avait été posé en bloquant par
accident ; ce fichier corrige la méthode pour les futurs déploiements).
"""
from alembic import op


revision = "bc1_import_measurement_lookup"
down_revision = "0063_merge_import_superstream"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_measurement_points_project_capture_seq",
            "measurement_points",
            ["project_id", "capture_id", "seq"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_measurement_points_project_capture_seq",
            table_name="measurement_points",
            postgresql_concurrently=True,
            if_exists=True,
        )
