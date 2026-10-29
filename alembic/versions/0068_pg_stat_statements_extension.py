"""Enable pg_stat_statements extension for query profiling.

Revision ID: 0068_pg_stat_statements_extension
Revises: 0067_kpi_physical_cell_indexes

Prérequis infra : la libraire doit être pré-chargée via
`shared_preload_libraries=pg_stat_statements` dans la commande du
service `db` (deploy/docker-compose.yml 0.97.4). L'extension elle-même
est créée ici pour que l'audit SQL soit versionné (jamais en `psql`
manuel). Idempotent : `CREATE EXTENSION IF NOT EXISTS`.
"""
from alembic import op


revision = "0068_pg_stat_statements_extension"
down_revision = "0067_kpi_physical_cell_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
