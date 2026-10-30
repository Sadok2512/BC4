"""Force password change and revoke pre-rotation tokens.

Revision ID: 0074_auth_password_change
Revises: 0073_nmf_cell_identity
"""
from alembic import op
import sqlalchemy as sa


revision = "0074_auth_password_change"
down_revision = "0073_nmf_cell_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "app_user",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_user", "password_changed_at")
    op.drop_column("app_user", "must_change_password")
