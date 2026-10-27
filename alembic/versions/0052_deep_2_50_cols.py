"""Add 261 NFF 2.50 non-structural columns to nmf_event_deep (symmetric 0050).

Phase 2.2a 11e passe : captures `decode_level='deep'` ratent le re-decode
car ADD COLUMN du 0050 n'a touché que `nmf_event_light`. nmf_event_deep
est une table PARTITIONNÉE (une partition par capture_id) ; ADD COLUMN
sur la table parent se propage automatiquement aux partitions.

Revision ID : 0052_deep_2_50_cols
Revises    : 0051_param_occurrence_fk_index
"""
import json
from pathlib import Path
from alembic import op

revision = "0052_deep_2_50_cols"
down_revision = "0051_param_occurrence_fk_index"
branch_labels = None
depends_on = None


def _load_cols():
    for p in (
        Path(__file__).parent.parent.parent / "scripts/catalog/missing_cols_2.50_simple.json",
        Path("/app/scripts/catalog/missing_cols_2.50_simple.json"),
    ):
        if p.exists():
            data = json.loads(p.read_text())
            return [(row[0], row[1]) for row in data]
    return []


def upgrade() -> None:
    cols = _load_cols()
    assert cols, "missing_cols_2.50_simple.json not found — cannot add columns"
    # Ad-hoc gap de la 7e passe : dci_dci_count avait été ajouté manuellement
    # sur la base live, mais jamais par 0050. A replayed empty database must
    # receive it on Light as well as Deep or a real import fails at COPY.
    extra = [("dci_dci_count", "DOUBLE PRECISION")]
    all_cols = cols + [e for e in extra if e[0] not in {c[0] for c in cols}]
    op.execute('ALTER TABLE nmf_event_light ADD COLUMN IF NOT EXISTS "dci_dci_count" DOUBLE PRECISION')
    for col, pg_type in all_cols:
        op.execute(f'ALTER TABLE nmf_event_deep ADD COLUMN IF NOT EXISTS "{col}" {pg_type}')
    print(f"[0052] added {len(all_cols)} columns to nmf_event_deep (partitions propagées)")


def downgrade() -> None:
    cols = _load_cols()
    extra = [("dci_dci_count", "DOUBLE PRECISION")]
    all_cols = cols + [e for e in extra if e[0] not in {c[0] for c in cols}]
    op.execute('ALTER TABLE nmf_event_light DROP COLUMN IF EXISTS "dci_dci_count"')
    for col, _ in reversed(all_cols):
        op.execute(f'ALTER TABLE nmf_event_deep DROP COLUMN IF EXISTS "{col}"')
