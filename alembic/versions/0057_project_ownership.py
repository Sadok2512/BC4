"""L1 project owner and visibility for a clean BC4 database.

The reset database contains no project, so both columns can be introduced with
their final NOT NULL contract.  This migration deliberately contains no legacy
project mapping and no reference data.
"""
from alembic import op
import sqlalchemy as sa

revision = "0057_project_ownership"
down_revision = "0056_range_violations"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("projects", sa.Column("owner_id", sa.String(), nullable=False))
    op.add_column("projects", sa.Column("visibility", sa.String(), nullable=False))
    op.create_foreign_key(
        "fk_projects_owner_id_app_user", "projects", "app_user", ["owner_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_projects_visibility", "projects", "visibility IN ('private','public')"
    )

    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_visibility", "projects", ["visibility"])
    # Access policy is deliberately not encoded as an admin bypass here:
    # My/All must use owner/public/share predicates in L1 service code.


def downgrade() -> None:
    op.drop_index("ix_projects_visibility", table_name="projects")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("ck_projects_visibility", "projects", type_="check")
    op.drop_constraint("fk_projects_owner_id_app_user", "projects", type_="foreignkey")
    op.drop_column("projects", "visibility")
    op.drop_column("projects", "owner_id")
