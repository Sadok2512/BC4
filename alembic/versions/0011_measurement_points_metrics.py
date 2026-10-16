"""measurement_points : colonnes métriques (nullable) — Keystone 0.24.0

Phase 2 skeleton : les colonnes de métriques radio (RSRQ, SINR, RSSI,
CQI, rang MIMO, puissance TX) et de débit uplink (`thrpt_ul`) sont
ajoutées à `measurement_points` en **NULL par défaut**. La colonne
historique `dl` continue de porter le débit DL le temps que Phase 1
(mapping champ→métrique) soit prouvée.

Jusqu'à Phase 1 validée : AUCUN de ces champs n'est peuplé par le
pipeline — on populate uniquement l'armature géographique (capture_id,
seq, ts, system, operator, band, lat, lng) depuis `stg_measurement_raw`.
Un champ non mappé reste NULL, pas 0 — déclaration d'écart, pas invention.

Revision ID: 0011_measurement_points_metrics
Revises: 0010_stg_measurement_raw
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_measurement_points_metrics"
down_revision = "0010_stg_measurement_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("measurement_points") as batch:
        batch.add_column(sa.Column("rsrq", sa.Float(), nullable=True))
        batch.add_column(sa.Column("rssi", sa.Float(), nullable=True))
        batch.add_column(sa.Column("cqi", sa.Float(), nullable=True))
        batch.add_column(sa.Column("mimo_rank", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("tx_power", sa.Float(), nullable=True))
        # dl existe déjà (débit DL). thrpt_ul est le symétrique uplink.
        batch.add_column(sa.Column("thrpt_ul", sa.Float(), nullable=True))
        # event_code source — utile pour tracer d'où vient un point
        # (CELLMEAS, CQI, PHRATE…) sans ré-interroger stg_measurement_raw.
        batch.add_column(sa.Column("event_code", sa.String(), nullable=True))
        # Les mesures NMF n'ont pas de "service"/"dep"/"site" (concepts
        # du seed B0). Pour les points issus de `stg_measurement_raw`
        # on les laisse NULL plutôt que d'inventer. Les seeds existants
        # satisfont déjà la contrainte NOT NULL avant alteration.
        batch.alter_column("service", nullable=True)
        batch.alter_column("dep", nullable=True)
        batch.alter_column("site", nullable=True)
        # Idem pour `operator` et `tech` : pattern populate.py
        # (operator NULL en base, COALESCE au SELECT → "non attribué").
        batch.alter_column("operator", nullable=True)
        batch.alter_column("tech", nullable=True)
        # `band` reste NOT NULL : on dérive toujours de freq via
        # bc4_enrich ; si inconnu, on skip plutôt que d'inventer.
        # → Non, on peut aussi en avoir sans band. Alterne.
        batch.alter_column("band", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("measurement_points") as batch:
        # Downgrade NOT NULL requires existing data to satisfy — downgrade
        # best-effort : si la table contient des lignes avec NULL, l'
        # downgrade échouera (safe par défaut).
        batch.alter_column("band", nullable=False)
        batch.alter_column("tech", nullable=False)
        batch.alter_column("operator", nullable=False)
        batch.alter_column("service", nullable=False)
        batch.alter_column("dep", nullable=False)
        batch.alter_column("site", nullable=False)
        batch.drop_column("event_code")
        batch.drop_column("thrpt_ul")
        batch.drop_column("tx_power")
        batch.drop_column("mimo_rank")
        batch.drop_column("cqi")
        batch.drop_column("rssi")
        batch.drop_column("rsrq")
