"""catalog_release table — versionned catalog artefact tracking.

NFF 2.50 pack : /home/devmat/BC4/specs/nff_2.50_pack.zip (282 events, 4393
fields). Le catalog est GÉNÉRÉ par scripts/catalog/build_catalog.py depuis
le CSV — aucune édition à la main. Chaque build écrit une ligne dans
catalog_release ; un seul `is_current=TRUE` à la fois.

Revision ID: 0048_catalog_release
Revises: 0047_nmf_string_columns
"""
from alembic import op

revision = "0048_catalog_release"
down_revision = "0047_nmf_string_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE catalog_release (
            version              VARCHAR PRIMARY KEY,
            spec_version         VARCHAR NOT NULL,
            decoder_min_version  VARCHAR NOT NULL,
            sha256               VARCHAR(64) NOT NULL,
            n_categories         INTEGER NOT NULL,
            n_metrics            INTEGER NOT NULL,
            n_leaves             INTEGER NOT NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            changelog            TEXT,
            is_current           BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    # Partial unique index : au plus UNE ligne is_current à la fois.
    op.execute(
        "CREATE UNIQUE INDEX ux_catalog_release_current "
        "ON catalog_release (is_current) WHERE is_current = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_catalog_release_current")
    op.execute("DROP TABLE IF EXISTS catalog_release")
