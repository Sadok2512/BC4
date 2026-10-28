"""Freeze the project parsing contract when an import job is enqueued.

Legacy jobs remain explicitly unsnapshotted (NULL).  New jobs are written with
all six fields by the application; no historical value is reconstructed.
"""
from alembic import op
import sqlalchemy as sa


revision = "0061_import_job_parsing_snapshot"
down_revision = "0060_light_dci_count_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nmf_import_jobs", sa.Column("decode_level", sa.String(), nullable=True))
    op.add_column("nmf_import_jobs", sa.Column("binning_mode", sa.String(), nullable=True))
    op.add_column("nmf_import_jobs", sa.Column("temporal_resolution", sa.String(), nullable=True))
    op.add_column("nmf_import_jobs", sa.Column("spatial_bin_m", sa.Integer(), nullable=True))
    op.add_column(
        "nmf_import_jobs",
        sa.Column("aggregation_contract_version", sa.String(), nullable=True),
    )
    op.add_column("nmf_import_jobs", sa.Column("decoder_version", sa.String(), nullable=True))
    op.create_check_constraint(
        "nmf_import_jobs_decode_level_check",
        "nmf_import_jobs",
        "decode_level IS NULL OR decode_level IN ('light','deep')",
    )
    op.create_check_constraint(
        "nmf_import_jobs_binning_mode_check",
        "nmf_import_jobs",
        "binning_mode IS NULL OR binning_mode IN ('temporal','spatial')",
    )
    op.create_check_constraint(
        "nmf_import_jobs_resolution_check",
        "nmf_import_jobs",
        "(binning_mode IS NULL AND temporal_resolution IS NULL AND spatial_bin_m IS NULL) OR "
        "(binning_mode='temporal' AND temporal_resolution IN "
        "('native','1ms','10ms','100ms','1s') AND spatial_bin_m IS NULL) OR "
        "(binning_mode='spatial' AND temporal_resolution IS NULL AND spatial_bin_m IN (10,25,50,100))",
    )


def downgrade() -> None:
    op.drop_constraint("nmf_import_jobs_resolution_check", "nmf_import_jobs", type_="check")
    op.drop_constraint("nmf_import_jobs_binning_mode_check", "nmf_import_jobs", type_="check")
    op.drop_constraint("nmf_import_jobs_decode_level_check", "nmf_import_jobs", type_="check")
    for column in (
        "decoder_version",
        "aggregation_contract_version",
        "spatial_bin_m",
        "temporal_resolution",
        "binning_mode",
        "decode_level",
    ):
        op.drop_column("nmf_import_jobs", column)
