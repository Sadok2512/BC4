"""Dictionnaire v2 : colonnes d'enrichissement sur param_occurrence (0.45.0)

Ajoute :
- ``param_key`` : chemin canonique (CHOICE collapsé, index drops).
- ``display_name`` : nom 3GPP natif (dernier segment).
- ``choice_of`` : nom du CHOICE parent si la feuille vient d'un CHOICE,
  sinon NULL.
- ``discriminators`` : jsonb {bearer, rlc_mode, direction, event, earfcn,
  pci, bwp_id, scell_index, measObjectId, reportConfigId, …}.
- ``origin`` : ``network_config | ue_capability | ue_report`` déduit du
  message porteur.
- ``is_identifier`` : True pour les identités techniques (rrc-TransactionIdentifier,
  measId, drb-Identity, logicalChannelIdentity, eps-BearerIdentity, …).
  Exclues de l'arbre Paramètres (catalog) ; incluses dans raw.
- ``functional_group`` : groupe pré-calculé pour l'arbre catalog
  (``Identité cellule``, ``Mesures critères``, ``MAC-DRX``, …).

Index :
- ``(project_id, param_key)`` — lookup catalog + distribution.
- ``(project_id, origin, message)`` — arbre catalog filtre par origin.

Discipline additive stricte : aucune colonne existante modifiée.
Backfill : NULL par défaut ; le remplissage se fait au prochain
``POST /_rebuild_param_occurrence`` (``populate_param_occurrence``
tient compte des nouvelles colonnes).

Revision ID: 0017_param_occurrence_dict_v2
Revises: 0016_mp_ecgi_cell_ref_geo
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0017_param_occurrence_dict_v2"
down_revision = "0016_mp_ecgi_cell_ref_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("param_occurrence") as batch:
        batch.add_column(sa.Column("param_key",         sa.Text(),    nullable=True))
        batch.add_column(sa.Column("display_name",      sa.String(),  nullable=True))
        batch.add_column(sa.Column("choice_of",         sa.String(),  nullable=True))
        batch.add_column(sa.Column("discriminators",    JSONB(),      nullable=True))
        batch.add_column(sa.Column("origin",            sa.String(),  nullable=True))
        batch.add_column(sa.Column("is_identifier",     sa.Boolean(), nullable=True, server_default=sa.false()))
        batch.add_column(sa.Column("functional_group",  sa.String(),  nullable=True))
    op.create_index("ix_param_occ_param_key", "param_occurrence", ["project_id", "param_key"])
    op.create_index("ix_param_occ_origin",    "param_occurrence", ["project_id", "origin", "message"])


def downgrade() -> None:
    op.drop_index("ix_param_occ_origin",    table_name="param_occurrence")
    op.drop_index("ix_param_occ_param_key", table_name="param_occurrence")
    with op.batch_alter_table("param_occurrence") as batch:
        batch.drop_column("functional_group")
        batch.drop_column("is_identifier")
        batch.drop_column("origin")
        batch.drop_column("discriminators")
        batch.drop_column("choice_of")
        batch.drop_column("display_name")
        batch.drop_column("param_key")
