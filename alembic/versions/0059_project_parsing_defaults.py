"""Project parsing defaults and immutable capture/job snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0059_project_parsing_defaults"
down_revision = "0058_project_shares"
branch_labels = None
depends_on = None

TARGETS = ("projects", "nmf_capture", "nmf_decode_job")

def _add_contract(table: str, *, include_decode: bool) -> None:
    if include_decode:
        op.add_column(table, sa.Column("decode_level", sa.String(), nullable=False, server_default="light"))
        op.create_check_constraint(f"{table}_parse_decode_level_check", table, "decode_level IN ('light','deep')")
    op.add_column(table, sa.Column("binning_mode", sa.String(), nullable=False, server_default="temporal"))
    op.add_column(table, sa.Column("temporal_resolution", sa.String(), nullable=True, server_default="native"))
    op.add_column(table, sa.Column("spatial_bin_m", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("aggregation_contract_version", sa.String(), nullable=False, server_default="query-binning-v1"))
    op.create_check_constraint(f"{table}_binning_mode_check", table, "binning_mode IN ('temporal','spatial')")
    op.create_check_constraint(
        f"{table}_parse_resolution_check", table,
        "(binning_mode='temporal' AND temporal_resolution IN ('native','1ms','10ms','100ms','1s') AND spatial_bin_m IS NULL) OR "
        "(binning_mode='spatial' AND temporal_resolution IS NULL AND spatial_bin_m IN (10,25,50,100))",
    )

def upgrade() -> None:
    op.add_column("projects", sa.Column("parse_decode_level", sa.String(), nullable=False, server_default="light"))
    op.add_column("projects", sa.Column("parse_binning_mode", sa.String(), nullable=False, server_default="temporal"))
    op.add_column("projects", sa.Column("parse_temporal_resolution", sa.String(), nullable=True, server_default="native"))
    op.add_column("projects", sa.Column("parse_spatial_bin_m", sa.Integer(), nullable=True))
    op.create_check_constraint("projects_parse_decode_level_check", "projects", "parse_decode_level IN ('light','deep')")
    op.create_check_constraint("projects_parse_binning_mode_check", "projects", "parse_binning_mode IN ('temporal','spatial')")
    op.create_check_constraint("projects_parse_resolution_check", "projects", "(parse_binning_mode='temporal' AND parse_temporal_resolution IN ('native','1ms','10ms','100ms','1s') AND parse_spatial_bin_m IS NULL) OR (parse_binning_mode='spatial' AND parse_temporal_resolution IS NULL AND parse_spatial_bin_m IN (10,25,50,100))")
    _add_contract("nmf_capture", include_decode=False)
    _add_contract("nmf_decode_job", include_decode=True)

def downgrade() -> None:
    for table, include_decode in (("nmf_decode_job", True), ("nmf_capture", False)):
        op.drop_constraint(f"{table}_parse_resolution_check", table, type_="check")
        op.drop_constraint(f"{table}_binning_mode_check", table, type_="check")
        if include_decode:
            op.drop_constraint(f"{table}_parse_decode_level_check", table, type_="check")
        for column in ("aggregation_contract_version", "spatial_bin_m", "temporal_resolution", "binning_mode"):
            op.drop_column(table, column)
        if include_decode:
            op.drop_column(table, "decode_level")
    op.drop_constraint("projects_parse_resolution_check", "projects", type_="check")
    op.drop_constraint("projects_parse_binning_mode_check", "projects", type_="check")
    op.drop_constraint("projects_parse_decode_level_check", "projects", type_="check")
    for column in ("parse_spatial_bin_m", "parse_temporal_resolution", "parse_binning_mode", "parse_decode_level"):
        op.drop_column("projects", column)
