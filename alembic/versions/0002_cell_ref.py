"""cell_ref + reference_import (B1-réf)

Revision ID: 0002_cell_ref
Revises: 0001_initial
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "0002_cell_ref"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cell_ref",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("snapshot_date", sa.String(), nullable=True),
        sa.Column("rat", sa.String(), nullable=False, index=True),
        sa.Column("vendor", sa.String(), nullable=True),
        sa.Column("eci", sa.String(), nullable=True, index=True),
        sa.Column("nci", sa.String(), nullable=True, index=True),
        sa.Column("enodebid", sa.String(), nullable=True, index=True),
        sa.Column("pci", sa.Integer(), nullable=True),
        sa.Column("band_src", sa.String(), nullable=True),
        sa.Column("band_3gpp", sa.String(), nullable=True, index=True),
        sa.Column("techno", sa.String(), nullable=True),
        sa.Column("earfcn", sa.Integer(), nullable=True),
        sa.Column("azimuth", sa.Float(), nullable=True),
        sa.Column("tilt", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("coverage", sa.String(), nullable=True),
        sa.Column("cell_class", sa.String(), nullable=True),
        sa.Column("etat", sa.String(), nullable=True),
        sa.Column("dor", sa.String(), nullable=True, index=True),
        sa.Column("dr", sa.String(), nullable=True, index=True),
        sa.Column("plaque", sa.String(), nullable=True, index=True),
        sa.Column("site_id", sa.String(), nullable=True, index=True),
        sa.Column("site_name", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("cell_op_leader", sa.String(), nullable=True),
        # Geometry: PostGIS POINT WGS84. PostGIS extension créée en 0001.
        sa.Column(
            "geom",
            sa.Text(),  # placeholder for raw column type; we'll fix via raw SQL below.
            nullable=True,
        ),
        sa.Column("reference_import_id", sa.String(), nullable=True),
    )

    # Switch geom to a real GEOMETRY(POINT, 4326) and build a GIST index.
    op.execute("ALTER TABLE cell_ref ALTER COLUMN geom TYPE geometry(Point, 4326) USING NULL")
    op.execute("CREATE INDEX ix_cell_ref_geom ON cell_ref USING GIST (geom)")

    op.create_table(
        "reference_import",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("snapshot_date", sa.String(), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_loaded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reference_import")
    op.execute("DROP INDEX IF EXISTS ix_cell_ref_geom")
    op.drop_table("cell_ref")
