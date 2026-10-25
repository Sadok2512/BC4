"""nmf_event_light_ext — narrow extension table for NFF 2.50 fields not
mapped to a dedicated column in nmf_event_light.

BC3 Phase 2.2a arbitrage : au lieu d'ajouter 336+ colonnes à nmf_event_light
pour les 113 events corpus × leurs champs 2.50 nouveaux (BC3 attendait
<100, observé 336/451 — NFF 2.50 CSV expose plus de champs par event que
1.5.1 n'en gardait), on route les nouveaux champs vers cette table narrow
(project_id, capture_id, second, event_code, field, value JSONB).

- Downgrade : drop table (0 impact sur light).
- Décodeur 1.6.0 (Phase 2.2b) : écrira ici pour les codes `event.field`
  qui ne matchent pas une colonne existante.
- Scanner les 2.6x `unk_<EVENT>_<idx>` : même table (field="unk_...").

Revision ID : 0049_nmf_event_light_ext
Revises    : 0048_catalog_release
"""
from alembic import op

revision = "0049_nmf_event_light_ext"
down_revision = "0048_catalog_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE nmf_event_light_ext (
            id             BIGSERIAL PRIMARY KEY,
            project_id     VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            capture_id     VARCHAR NOT NULL,
            seq            INTEGER NOT NULL,
            second         BIGINT  NOT NULL,
            event_code     TEXT    NOT NULL,
            field          TEXT    NOT NULL,
            value          JSONB,
            decoder_version TEXT   NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_nmf_event_light_ext_lookup "
        "ON nmf_event_light_ext (project_id, capture_id, event_code, field)"
    )
    op.execute(
        "CREATE INDEX ix_nmf_event_light_ext_second "
        "ON nmf_event_light_ext (project_id, capture_id, second)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nmf_event_light_ext_second")
    op.execute("DROP INDEX IF EXISTS ix_nmf_event_light_ext_lookup")
    op.execute("DROP TABLE IF EXISTS nmf_event_light_ext")
