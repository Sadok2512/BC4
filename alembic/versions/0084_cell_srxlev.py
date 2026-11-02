"""Add cell_srxlev column (NFF 2.50 CELLMEAS LTE field #10, 3GPP TS 36.304 §5.2.3).

Revision ID: 0084_cell_srxlev
Revises: 0083_procedure_evidence
Create Date: 2026-11-02

Needed to persist the LTE Srxlev measurement that NFF 2.50 publishes at
position #10 of the CELLMEAS cell block.  The decoder patch in 0.123.2
declares `cell.srxlev` to keep positional alignment with SINR (field
#11) ; without this column the COPY INTO nmf_event_light /
nmf_event_group fails with UndefinedColumn.

Additive, idempotent, backward-compatible : legacy captures without the
field continue to decode (value stays NULL).
"""
from alembic import op


revision = "0084_cell_srxlev"
down_revision = "0083_procedure_evidence"
branch_labels = None
depends_on = None


COL = "cell_srxlev"


def upgrade():
    for table in (
        "nmf_event_light",
        "nmf_event_deep",
        "nmf_event_light_group",
        "nmf_event_group",
    ):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {COL} double precision")


def downgrade():
    for table in (
        "nmf_event_light",
        "nmf_event_deep",
        "nmf_event_light_group",
        "nmf_event_group",
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {COL}")
