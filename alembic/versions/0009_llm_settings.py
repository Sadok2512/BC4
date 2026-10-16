"""settings_llm (B2 — config LLM persistée)

Revision ID: 0009_llm_settings
Revises: 0008_param_occurrence
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "0009_llm_settings"
down_revision = "0008_param_occurrence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings_llm",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        # Clé chiffrée Fernet (base64). NULL = pas de clé stockée.
        # NE JAMAIS logger ni renvoyer en clair.
        sa.Column("api_key_cipher", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Garantir le singleton (id=1).
    op.execute("INSERT INTO settings_llm (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("settings_llm")
