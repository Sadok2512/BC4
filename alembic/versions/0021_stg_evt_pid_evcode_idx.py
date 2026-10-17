"""0.48.0 — index (project_id, event_code) sur stg_event_raw

Correctif perf /kpi/catalog. ``compute_transfers`` scanne
``stg_event_raw WHERE project_id = :pid AND event_code IN
('CMDREQ','DSUMMARY')`` à chaque appel. Sans index composite
``(project_id, event_code)``, le planner tombait sur un ``Parallel
Seq Scan`` : ~1.4 M lignes scannées, ~700 ms chaud (plusieurs
secondes à froid). Appelé 7× par ``build_catalog_v2_response``
(5× ``transfers_dms`` + 2× ``transfers_table``), ça explique le
``/kpi/catalog`` à 12.7 s mesuré en lot 1.21.1.

Mesure EXPLAIN ANALYZE sur REF (1 414 445 lignes totales,
254 CMDREQ+DSUMMARY) **avant** index :
    Parallel Seq Scan on stg_event_raw ... 688 ms (hit=13 846 read=86 385)

Après index : Index Scan direct ciblé sur ~254 lignes → attendu <5 ms.

**Jamais de données fabriquées** : index pur, pas de touch des rows.

Revision ID: 0021_stg_evt_pid_evcode_idx
Revises: 0020_mp_lat_lng_nullable
Create Date: 2026-10-17
"""
from __future__ import annotations

from alembic import op

revision: str = "0021_stg_evt_pid_evcode_idx"
down_revision: str = "0020_mp_lat_lng_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS → tolérant si quelqu'un l'a déjà créé à la main.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stg_event_raw_project_event_code "
        "ON stg_event_raw (project_id, event_code)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_stg_event_raw_project_event_code")
