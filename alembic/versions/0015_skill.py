"""Skills Center (0.38.0 — skills Markdown déclaratifs)

Table ``skill`` + index. Chaque entrée est un fichier Markdown avec
frontmatter YAML (voir ``app/services/skills.py`` pour la grammaire).
Garanties au niveau DB :

- ``(slug, version)`` est **unique**. Un même slug peut exister en
  plusieurs versions ; l'historique n'est jamais écrasé silencieusement.
- Un seul actif par slug : contrainte applicative (ActivateHandler
  passe les autres versions du même slug en ``archived``). Elle n'est
  pas forcée en DB pour permettre l'ingestion/validation sans conflit
  (le validateur refuse une activation si une autre version active).
- ``status`` : enum textuel ``draft | validated | active | archived``.
  Pas de type enum PG dédié — on garde la souplesse de requêtage.

Discipline :
- Additive STRICTE : aucune autre table n'est touchée.
- ``body_md`` est ``Text`` sans index full-text (ni critère métier à
  ce stade — le validateur fait les contrôles au `/validate`).
- ``triggers``, ``tools_allowed``, ``render`` : ``JSONB`` listes de
  chaînes (format validé en Python, pas de contrainte SQL).

Revision ID: 0015_skill
Revises: 0014_stg_event_raw_and_file_meta
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0015_skill"
down_revision = "0014_stg_event_raw_and_file_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("triggers", JSONB(), nullable=False),
        sa.Column("tools_allowed", JSONB(), nullable=False),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("render", JSONB(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        # draft | validated | active | archived
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "validated_by",
            sa.String(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug", "version", name="uq_skill_slug_version"),
    )
    op.create_index("ix_skill_slug", "skill", ["slug"])
    op.create_index("ix_skill_status", "skill", ["status"])


def downgrade() -> None:
    op.drop_index("ix_skill_status", table_name="skill")
    op.drop_index("ix_skill_slug", table_name="skill")
    op.drop_table("skill")
