"""stg_event : attributs ts/freq/pci exposés par bc4_decoder 1.0.0

Revision ID: 0004_stg_event_decoder_fields
Revises: 0003_nmf_ingest
Create Date: 2026-10-15

Le décodeur canonique `bc4_decoder` expose trois attributs supplémentaires
par event : `ts` (horodatage ISO — ATTRIBUT seulement, jamais utilisé pour
l'ordre : l'ordre canonique reste `(capture_id, seq)` STRICT), `freq`
(EARFCN/UARFCN/ARFCN) et `pci` (PCI/PSC). On les persiste gratuitement :
ils tombent du décodeur sans surcoût et seront utiles côté analyseur.

Rappel ordre canonique : les tris et comparaisons ne se font JAMAIS sur
`ts`. Index existant `(project_id, capture_id, seq)` inchangé.
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_stg_event_decoder_fields"
down_revision = "0003_nmf_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stg_event", sa.Column("ts", sa.String(), nullable=True))
    op.add_column("stg_event", sa.Column("freq", sa.String(), nullable=True))
    op.add_column("stg_event", sa.Column("pci", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("stg_event", "pci")
    op.drop_column("stg_event", "freq")
    op.drop_column("stg_event", "ts")
