"""Reconstructed from DB state after container rebuild erased the original file.

Historique : la version originale 0047_nmf_string_columns.py avait été créée
hors-git (dans le volume de bc4-api-1) entre 0046 et 0048, puis perdue lors du
rebuild image main. La chaîne alembic a été momentanément recousue par
e2a5b96 (0048.down_revision = 0046). Ce fichier est la **reconstruction
explicite** depuis `\\d nmf_capture` live (projet BC4, 2026-10-25) :

    decode_level      text
    decoder_version   text
    schema_version    text
    format_version    text

Ces colonnes sont déjà `text` depuis 0031_nmf_decoder.py (CREATE TABLE
nmf_capture). Les ALTER COLUMN ... TYPE text ci-dessous sont donc idempotents
(Postgres optimise en no-op quand le type cible est identique). Le but du
fichier est de REMETTRE EN PLACE le maillon de chaîne manquant pour qu'un
`alembic upgrade head` sur base vide traverse 0046 → 0047 → 0048 → ... → 0052
sans KeyError.

Reconstruction uniquement — aucune donnée fabriquée, pas d'inférence sur ce que
contenait l'original. Si l'original avait d'autres ALTER (ex. élargissement
VARCHAR→TEXT sur d'autres tables), ils ont été implicitement absorbés par
0044_nmf_string_columns.py (déjà en git, applied) et 0049/0050/0052
(nmf_event_light_ext, light_2_50_cols, deep_2_50_cols — colonnes créées
directement en text).

Revision ID: 0047_nmf_string_columns
Revises: 0046_seed_pkeys
"""
from alembic import op


revision = "0047_nmf_string_columns"
down_revision = "0046_seed_pkeys"
branch_labels = None
depends_on = None


NMF_CAPTURE_TEXT_COLS = (
    "decode_level",
    "decoder_version",
    "schema_version",
    "format_version",
)


def upgrade() -> None:
    bind = op.get_bind()
    columns_to_change = []
    for col in NMF_CAPTURE_TEXT_COLS:
        data_type = bind.exec_driver_sql(
            """
            SELECT data_type
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'nmf_capture'
               AND column_name = %s
            """,
            (col,),
        ).scalar()
        if data_type != "text":
            columns_to_change.append(col)

    if not columns_to_change:
        return

    # nmf_metric_value selects decoder_version and filters on decode_level.
    # PostgreSQL rejects ALTER TYPE even for a binary-compatible conversion
    # while that dependency exists, so preserve and restore the view around
    # the actual changes only.
    view = bind.exec_driver_sql(
        "SELECT pg_get_viewdef('nmf_metric_value'::regclass, true)"
    ).scalar()
    op.execute("DROP VIEW IF EXISTS nmf_metric_value")

    for col in columns_to_change:
        op.execute(
            f"ALTER TABLE nmf_capture ALTER COLUMN {col} TYPE text USING {col}::text"
        )

    if view:
        op.execute("CREATE VIEW nmf_metric_value AS " + view)


def downgrade() -> None:
    pass
