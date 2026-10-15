"""app_user (B2 — comptes locaux)

Revision ID: 0005_app_user
Revises: 0004_stg_event_decoder_fields
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "0005_app_user"
down_revision = "0004_stg_event_decoder_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Rôles autorisés — fermés par CHECK : toute écriture hors de ce
        # vocabulaire échoue au niveau DB, pas seulement en Python.
        sa.CheckConstraint(
            "role IN ('admin','ingenieur','lecteur')",
            name="ck_app_user_role",
        ),
    )
    op.create_index("ix_app_user_email_lower", "app_user", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_user_email_lower", table_name="app_user")
    op.drop_table("app_user")
