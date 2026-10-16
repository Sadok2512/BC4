"""settings_llm: model_loop + daily_cap_usd + llm_usage (0.27.0)

Trois ajouts pour la maîtrise des coûts assistant :

1. `settings_llm.model_loop` : modèle utilisé par la boucle agent
   (tool-calling répétitif). Par défaut = `model` existant si NULL.
   Permet un modèle PAS CHER pour la boucle et un `model` cher
   réservé au probe / cas de haute qualité.

2. `settings_llm.daily_cap_usd` : plafond journalier USD. Si NULL,
   pas de plafond (comportement 0.26.x). Si posé, le moteur refuse
   d'appeler le LLM dès que la dépense du jour atteint ce cap.

3. Nouvelle table `llm_usage` : journalisation de chaque appel LLM
   (model, prompt_tokens, completion_tokens, estimated_cost_usd).
   Scope admin, pas d'identité abonné (c'est un log de méta-usage).

Revision ID: 0012_llm_cost_control
Revises: 0011_measurement_points_metrics
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_llm_cost_control"
down_revision = "0011_measurement_points_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings_llm") as batch:
        batch.add_column(sa.Column("model_loop", sa.String(), nullable=True))
        batch.add_column(sa.Column("daily_cap_usd", sa.Float(), nullable=True))

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("step", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_llm_usage_created_at", "llm_usage", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_table("llm_usage")
    with op.batch_alter_table("settings_llm") as batch:
        batch.drop_column("daily_cap_usd")
        batch.drop_column("model_loop")
