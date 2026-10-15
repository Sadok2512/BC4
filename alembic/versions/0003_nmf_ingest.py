"""nmf_file + stg_event + colonnes d'ingestion sur projects (B1-ingest)

Revision ID: 0003_nmf_ingest
Revises: 0002_cell_ref
Create Date: 2026-10-15

Un projet = un lot de logs NMF. Tout est scopé `project_id`. Les colonnes
ajoutées à `projects` portent le résumé rempli à l'ingestion (jamais devinées
sans comptage réel) ; les projets seedés B0 restent inchangés : les colonnes
sont nullable, pas de valeur par défaut magique.

`stg_event` est la staging aplatie du décodeur NMF (signalisation + GPS
rattaché), ordonnée par `(capture_id, seq)` STRICT — JAMAIS par `ts`.

Aucune identité d'abonné en table : la deny-list du décodeur protège contre
IMSI/MSISDN/TMSI ; `payload_hex` reste brut, les champs non-identité ne sont
pas masqués.
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_nmf_ingest"
down_revision = "0002_cell_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- Colonnes d'ingestion sur `projects` (nullable, sans toucher au seed) -----
    op.add_column("projects", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("actor", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("status_ingest", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("operators_plmn", sa.JSON(), nullable=True))
    op.add_column("projects", sa.Column("technos_seen", sa.JSON(), nullable=True))
    op.add_column("projects", sa.Column("n_captures_ingest", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("n_events_ingest", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("gps_coverage_pct", sa.Float(), nullable=True))

    # ----- nmf_file -----
    op.create_table(
        "nmf_file",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),  # pending/decoding/done/error
        sa.Column("decoder_version", sa.String(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("n_captures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_gps", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("project_id", "sha256", name="uq_nmf_file_project_sha"),
    )

    # ----- stg_event (staging décodé, scopée projet, ordre canonique capture_id,seq) -----
    op.create_table(
        "stg_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "nmf_file_id",
            sa.String(),
            sa.ForeignKey("nmf_file.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("capture_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_code", sa.String(), nullable=True),
        sa.Column("system", sa.String(), nullable=True),  # LTE / NR
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("payload_hex", sa.Text(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
    )
    # Ordre canonique `(capture_id, seq)` — jamais `ts`.
    op.create_index(
        "ix_stg_event_capture_seq",
        "stg_event",
        ["project_id", "capture_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_stg_event_capture_seq", table_name="stg_event")
    op.drop_table("stg_event")
    op.drop_table("nmf_file")
    for col in (
        "gps_coverage_pct",
        "n_events_ingest",
        "n_captures_ingest",
        "technos_seen",
        "operators_plmn",
        "status_ingest",
        "actor",
        "created_at",
    ):
        op.drop_column("projects", col)
