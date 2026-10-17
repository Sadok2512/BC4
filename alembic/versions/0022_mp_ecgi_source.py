"""0.48.0 — colonne measurement_points.ecgi_source

Jusqu'à 0.47.3, la colonne était créée **par le handler** via
``_ensure_mp_ecgi_source(db)`` dans ``app/measure/ecgi.py`` :
``ALTER TABLE measurement_points ADD COLUMN IF NOT EXISTS ecgi_source
VARCHAR`` à chaque appel de ``POST /kpi/_populate_ecgi``.

Problèmes :
- Du **DDL dans un handler** → acquisition d'``AccessExclusiveLock``
  sur une table hot pendant une requête HTTP. Cascade de locks si
  d'autres SELECT /kpi/* / /dict/* sont en cours ou en idle in
  transaction.
- Impossible à versionner proprement (le schéma dérive silencieusement
  entre deux déploiements).
- Incident 2026-10-17 ~19:14 : l'ALTER TABLE lancé par
  ``_populate_ecgi`` a bloqué 9 requêtes /kpi/* simultanées pendant
  25 min parce que 2 sessions SQLAlchemy orphelines (debug script
  TaskStop'd) tenaient un RowShareLock sur mp.

Correctif (0.48.0) :
- Cette migration crée la colonne (idempotente ``IF NOT EXISTS``).
- Le code ``_ensure_mp_ecgi_source`` est supprimé.
- ``_propagate_to_mp`` ne touche plus au schéma ; si la colonne
  manque il renvoie 409 "migration manquante : alembic upgrade head".

Revision ID: 0022_mp_ecgi_source
Revises: 0021_stg_event_project_event_code_idx
Create Date: 2026-10-17
"""
from __future__ import annotations

from alembic import op

revision: str = "0022_mp_ecgi_source"
down_revision: str = "0021_stg_evt_pid_evcode_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE measurement_points "
        "ADD COLUMN IF NOT EXISTS ecgi_source VARCHAR"
    )


def downgrade() -> None:
    # Downgrade propre si personne n'a encore écrit dedans.
    op.execute("ALTER TABLE measurement_points DROP COLUMN IF EXISTS ecgi_source")
