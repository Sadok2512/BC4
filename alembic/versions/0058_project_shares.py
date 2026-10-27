"""Project shares for named read-only collaborators."""
from alembic import op
import sqlalchemy as sa

revision = "0058_project_shares"
down_revision = "0057_project_ownership"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "project_share",
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="project_share_pkey"),
    )
    op.create_index("ix_project_share_user_id", "project_share", ["user_id"])

def downgrade() -> None:
    op.drop_index("ix_project_share_user_id", table_name="project_share")
    op.drop_table("project_share")
