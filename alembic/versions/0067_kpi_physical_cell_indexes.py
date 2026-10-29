"""KPI physical-cell lookup indexes.

Revision ID: 0067_kpi_physical_cell_indexes
Revises: bc1_decoder_1_8_1_cells
"""

from alembic import op


revision = "0067_kpi_physical_cell_indexes"
down_revision = "bc1_decoder_1_8_1_cells"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_nmf_cell_second_metric_cell_seq",
        "nmf_cell_second",
        ["project_id", "capture_id", "event_code", "metric_code", "cell_index", "seq_first"],
        unique=False,
        postgresql_include=["second", "seq_last", "value", "weight"],
    )
    op.create_index(
        "ix_nmf_light_group_cell_type_seq",
        "nmf_event_light_group",
        ["project_id", "capture_id", "group_name", "cell_type", "seq", "identity"],
        unique=False,
        postgresql_include=["cell_pci", "cell_ch"],
    )


def downgrade() -> None:
    op.drop_index("ix_nmf_light_group_cell_type_seq", table_name="nmf_event_light_group")
    op.drop_index("ix_nmf_cell_second_metric_cell_seq", table_name="nmf_cell_second")
