"""measurement_points : colonnes enrichies pour câblage décodeur 2.0.0 (0.30.0)

Keystone Phase 2 bis : enrichit `measurement_points` pour exploiter le
nouveau contrat `bc4-decoder 2.0.0::decode_nmf_file_full(path)` qui expose
`meta` (dl, ts, env, …) + events catégorisés (`category`) avec
`raw_fields` nommés sur les positions prouvées.

Discipline :
- Non-breaking : AUCUNE colonne existante n'est supprimée ni retypée.
  On ajoute des colonnes nullable + deux index (operator×rat, service×phase).
- `operator` dans `measurement_points` reste AUTORITAIRE depuis `#DL` du
  fichier (meta.dl). Un divergence avec le PLMN SIB1 **précédent** est
  simplement **déclarée** via `operator_source` + `operator_mismatch` ; on
  ne masque jamais le mismatch.
- Toute colonne non prouvée côté décodeur = NULL (jamais inventée).

Revision ID: 0013_measurement_enriched
Revises: 0012_llm_cost_control
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_measurement_enriched"
down_revision = "0012_llm_cost_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("measurement_points") as batch:
        # Provenance opérateur. Trois valeurs légales :
        #   'file' : opérateur dérivé de meta.dl (#DL du fichier) — AUTORITAIRE.
        #   'sib1' : opérateur dérivé du dernier PLMN SIB1 précédent
        #            dans l'ordre `(capture_id, seq)` (fallback si #DL absent/
        #            hors table DL_TO_OPERATOR).
        #   'none' : aucune des deux sources n'a produit un opérateur.
        batch.add_column(sa.Column("operator_source", sa.String(), nullable=True))
        # True si `operator` (depuis #DL) ≠ libellé déduit du PLMN SIB1
        # précédent. Déclaré, pas corrigé.
        batch.add_column(sa.Column("operator_mismatch", sa.Boolean(), nullable=True))
        # Service name verbatim (meta.ts nettoyé, préfixe d'index retiré).
        batch.add_column(sa.Column("service_name", sa.String(), nullable=True))
        # Dernier CMDREQ.service_action précédent (StartScript / StartHTTPTransfer /
        # Wait / Stop… etc.) attaché à l'event courant dans l'ordre canonique.
        batch.add_column(sa.Column("service_action", sa.String(), nullable=True))
        # Type normalisé depuis service_name OU service_action (voir
        # `app/measure/mapping.py::SERVICE_TYPE_RULES`). NULL si aucun match.
        batch.add_column(sa.Column("service_type", sa.String(), nullable=True))
        # Phase d'activité à l'instant du point : 'active' | 'wait' | 'idle'.
        batch.add_column(sa.Column("phase", sa.String(), nullable=True))
        # Contexte terrain depuis le nom de fichier (meta.env) : 'incar' | 'indoor'.
        batch.add_column(sa.Column("env", sa.String(), nullable=True))
        # Technologie radio dérivée du system_code (rat_code) exposé par le
        # décodeur : '7' → 'LTE', '9' → 'NR'. NULL sinon (jamais inventée).
        # On conserve `tech` existant (compat B0) mais `rat` est la source
        # autoritaire 2.0.0.
        batch.add_column(sa.Column("rat", sa.String(), nullable=True))
        # EARFCN du servant (cell0_earfcn) sur CELLMEAS, int. NULL sinon.
        batch.add_column(sa.Column("earfcn", sa.Integer(), nullable=True))

    op.create_index(
        "ix_measurement_points_project_operator_rat",
        "measurement_points",
        ["project_id", "operator", "rat"],
    )
    op.create_index(
        "ix_measurement_points_project_service_phase",
        "measurement_points",
        ["project_id", "service_type", "phase"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_points_project_service_phase",
        table_name="measurement_points",
    )
    op.drop_index(
        "ix_measurement_points_project_operator_rat",
        table_name="measurement_points",
    )
    with op.batch_alter_table("measurement_points") as batch:
        batch.drop_column("earfcn")
        batch.drop_column("rat")
        batch.drop_column("env")
        batch.drop_column("phase")
        batch.drop_column("service_type")
        batch.drop_column("service_action")
        batch.drop_column("service_name")
        batch.drop_column("operator_mismatch")
        batch.drop_column("operator_source")
