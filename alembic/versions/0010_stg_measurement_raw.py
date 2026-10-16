"""stg_measurement_raw : stream raw d'events mesure + débit (Keystone 0.24.0)

Table staging pour les événements NMF des catégories `measurement` et
`throughput` (nouveau décodeur 1.1.0). Elle garde la ligne CSV COMPLÈTE
dans `raw_fields` pour permettre la Phase 1 (mapping champ→métrique
par preuve + validation croisée RRC) **avant** tout mapping côté code.

Discipline :
- Scope strict `project_id` (CASCADE).
- Ordre canonique `(capture_id, seq)` ; `ts` est un ATTRIBUT seulement.
- `raw_fields` est un JSON array (de str) — pas de parsing précoce.
- Jamais d'identité abonné (déjà masquée par le décodeur à la source).

Revision ID: 0010_stg_measurement_raw
Revises: 0009_llm_settings
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0010_stg_measurement_raw"
down_revision = "0009_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stg_measurement_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "nmf_file_id",
            sa.String(),
            sa.ForeignKey("nmf_file.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capture_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.String(), nullable=True),
        sa.Column("event_code", sa.String(), nullable=False),
        # "measurement" | "throughput"
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("system", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        # Ligne CSV complète (jamais parsée côté SQL — Phase 1 lit en Python).
        sa.Column("raw_fields", JSONB(), nullable=False),
    )
    op.create_index(
        "ix_stg_meas_raw_project_code",
        "stg_measurement_raw",
        ["project_id", "event_code"],
    )
    op.create_index(
        "ix_stg_meas_raw_project_capture_seq",
        "stg_measurement_raw",
        ["project_id", "capture_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_stg_meas_raw_project_capture_seq", table_name="stg_measurement_raw")
    op.drop_index("ix_stg_meas_raw_project_code", table_name="stg_measurement_raw")
    op.drop_table("stg_measurement_raw")
