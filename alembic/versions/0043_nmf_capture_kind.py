"""Add nmf_capture.kind ('ue' | 'scanner') to classify Nemo captures.

Signal source (NFF 2.19) :
- `kind='scanner'` : events SCAN* (SCANCONFIG, STARTSCAN, CELLSCAN, OFDMSCAN)
  présents ET aucun event cell-scoped UE (CELLMEAS, CI). Fichier Ibflex-Scanner.
- `kind='ue'`      : CELLMEAS ou CI présent (= cellules UE observées).
- `kind IS NULL`   : capture non classifiable (ni SCAN* ni CELLMEAS/CI) — rare.

Décote G20 : les captures scanner-only n'ont jamais de `nmf_cell_second`
par design (aucune agrégation cell-scoped possible). G20 révisé en
`WHERE kind != 'scanner'` doit atteindre 0.

Revision ID: 0043_kind
Revises: 0042_utc_offset
"""
from alembic import op
import sqlalchemy as sa

revision = "0043_kind"
down_revision = "0042_utc_offset"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "nmf_capture",
        sa.Column("kind", sa.String(), nullable=True),
    )
    # CHECK contrainte libérale : jamais inventer, null autorisé.
    op.create_check_constraint(
        "nmf_capture_kind_check",
        "nmf_capture",
        "kind IS NULL OR kind IN ('ue', 'scanner')",
    )


def downgrade():
    op.drop_constraint("nmf_capture_kind_check", "nmf_capture", type_="check")
    op.drop_column("nmf_capture", "kind")
