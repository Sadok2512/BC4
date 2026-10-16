"""stg_event_raw + nmf_file.meta/source_path (0.30.0 — câblage décodeur 2.0.0)

Deuxième brique du câblage ``bc4-decoder 2.0.0`` :

1. **``stg_event_raw``** — staging brut de toutes les catégories non-signalling
   exposées par ``decode_nmf_file_full`` : ``cellmeas, cmdreq, data_action,
   data_request, data_summary, tx_power, cqi, lock, gps, other``. Les events
   ``signalling`` restent dans ``stg_event`` (contrat 1.0.0 préservé, backcompat
   RRC populate). Chaque ligne porte ``raw_fields`` en JSONB (dict nommé par
   position prouvée, fallback ``cN``). Ordre canonique ``(capture_id, seq)``.

2. **``nmf_file``** gagne les colonnes du ``meta`` fichier (``dl``, ``ts_label``,
   ``env``, ``start_at``, ``device_sw``, ``device_name``, ``product``,
   ``imei_present``, ``imsi_present``) + une colonne ``source_path`` qui
   référence le ``.nmf`` original PERSISTÉ (``/var/lib/bc4/nmf-source/<project_id>/<nmf_file_id>.nmf``).
   Jusqu'à présent, le fichier passait par un ``tempfile`` qui était supprimé
   après ingestion — la source brute est désormais conservée.

Discipline :
- Additive STRICTE : aucune colonne existante n'est retypée ni supprimée.
- Toutes les nouvelles colonnes sont ``nullable=True`` : les ``NmfFile`` déjà
  présents en base n'ont ni ``meta`` ni ``source_path`` et doivent le rester
  (déclaré, jamais inventé — un rebackfill éventuel passera par le script
  ``scripts/backfill_measurements.py``, pas par cette migration).
- Index ``(project_id, category)`` + ``(project_id, capture_id, seq)`` sur
  ``stg_event_raw`` pour nourrir ``populate_measurement_points``.

Revision ID: 0014_stg_event_raw_and_file_meta
Revises: 0013_measurement_enriched
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0014_stg_event_raw_and_file_meta"
down_revision = "0013_measurement_enriched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) nmf_file : meta file-level + source_path (nouvelles colonnes).
    # ------------------------------------------------------------------
    with op.batch_alter_table("nmf_file") as batch:
        # Chemin absolu du .nmf source persisté (ex. /var/lib/bc4/nmf-source/
        # <project_id>/<nmf_file_id>.nmf). NULL pour les ingestions antérieures
        # à 0.30.0 (jamais rebackfillé — déclaré ouvert).
        batch.add_column(sa.Column("source_path", sa.String(), nullable=True))
        # meta.dl brut (ex. "OFR" / "BYT" / "FREE"). Autoritaire pour `operator`.
        batch.add_column(sa.Column("dl", sa.String(), nullable=True))
        # meta.ts nettoyé (préfixe index + ".hsfx" retirés par le décodeur).
        # Nom de « script test session » dans l'outil NEMO.
        batch.add_column(sa.Column("ts_label", sa.String(), nullable=True))
        # meta.env : "incar" | "indoor" | NULL (par le CONTENU du nom).
        batch.add_column(sa.Column("env", sa.String(), nullable=True))
        # meta.start_time + meta.start_date concaténés (si disponibles) —
        # format TEXT, pas de parsing timezone (format source préservé).
        batch.add_column(sa.Column("start_at", sa.String(), nullable=True))
        batch.add_column(sa.Column("device_sw", sa.String(), nullable=True))
        batch.add_column(sa.Column("device_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("product", sa.String(), nullable=True))
        # Flags trace (jamais la valeur) — deny-list identité conservée.
        batch.add_column(sa.Column("imei_present", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("imsi_present", sa.Boolean(), nullable=True))

    # ------------------------------------------------------------------
    # 2) stg_event_raw : toutes les catégories NON-signalling du décodeur
    #    2.0.0 (``decode_nmf_file_full``). JAMAIS parsée côté SQL — le
    #    mapping Phase 2 lit ``raw_fields`` en Python.
    # ------------------------------------------------------------------
    op.create_table(
        "stg_event_raw",
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
        # cellmeas | cmdreq | data_action | data_request | data_summary |
        # tx_power | cqi | lock | gps | other
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("event_code", sa.String(), nullable=False),
        sa.Column("ts", sa.String(), nullable=True),
        sa.Column("system", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        # Dict NMF (nom prouvé → valeur str|None). Fallback ``cN`` pour les
        # positions non prouvées. JAMAIS re-aliasé en SQL — tout parse se
        # fait en Python (seule source de vérité : le décodeur).
        sa.Column("raw_fields", JSONB(), nullable=False),
    )
    op.create_index(
        "ix_stg_event_raw_project_category",
        "stg_event_raw",
        ["project_id", "category"],
    )
    op.create_index(
        "ix_stg_event_raw_project_capture_seq",
        "stg_event_raw",
        ["project_id", "capture_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stg_event_raw_project_capture_seq", table_name="stg_event_raw"
    )
    op.drop_index(
        "ix_stg_event_raw_project_category", table_name="stg_event_raw"
    )
    op.drop_table("stg_event_raw")

    with op.batch_alter_table("nmf_file") as batch:
        batch.drop_column("imsi_present")
        batch.drop_column("imei_present")
        batch.drop_column("product")
        batch.drop_column("device_name")
        batch.drop_column("device_sw")
        batch.drop_column("start_at")
        batch.drop_column("env")
        batch.drop_column("ts_label")
        batch.drop_column("dl")
        batch.drop_column("source_path")
