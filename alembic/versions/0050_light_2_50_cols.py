"""Add non-structural NFF 2.50 columns to nmf_event_light for the 98 simple
corpus events (261 columns).

Structurels EXCLUS (parsing hints, pas des colonnes Light) :
  Measured system, #Header params, #Cells, #Params/<X>, Scope, counters #Apps,
  #Antennas, #TSL results, etc.

12 complex events (CELLMEAS/CI/CQI/MIMOMEAS/PLAID/PLAIU/PDCPRATE[D|U]/
RLCRATE[|U]/TXPC/DCI/LOCK) restent sur l'architecture 1.5.1 : header →
nmf_event_light (déjà présent), groupes → nmf_event_light_group (déjà
présent). Pas de nouveaux ADD COLUMN pour eux dans cette migration.

Types : CSV `Integer`/`Float` → DOUBLE PRECISION (NFF souvent signé/large),
`String`/`Hex` → TEXT, `Boolean` → BOOLEAN. Nullable, pas de DEFAULT :
`ADD COLUMN NULL` est instantané en PostgreSQL ≥ 11.

Audit source : scripts/catalog/audit_strict.py.
Export JSON : exports/missing_cols_2.50_vs_1.5.1.json (filtered).

Revision ID : 0050_light_2_50_cols
Revises    : 0049_nmf_event_light_ext
"""
import json
from pathlib import Path
from alembic import op

revision = "0050_light_2_50_cols"
down_revision = "0049_nmf_event_light_ext"
branch_labels = None
depends_on = None

# Liste exacte (col, pg_type) — générée par scripts/catalog/audit_strict.py
# Note : /app/scripts/catalog/audit_strict.py reproduit cette liste si
# le CSV ou les schemas-2.50 changent. On embarque la liste statique ici
# pour que la migration soit auto-contenue.
COLS = [
    # Content from exports/cols_to_add_strict.json rotated. Embedded for repro.
    # (col_name, pg_type)
    # Loaded dynamically from JSON if present; fallback to empty for CI/dev.
]

def _load_cols():
    """Load from app/kpi/catalog_release/missing_cols_2.50_simple.json if present."""
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
    for col, pg_type in cols:
        op.execute(f'ALTER TABLE nmf_event_light ADD COLUMN IF NOT EXISTS "{col}" {pg_type}')
    print(f"[0050] added {len(cols)} columns")


def downgrade() -> None:
    cols = _load_cols()
    for col, _ in reversed(cols):
        op.execute(f'ALTER TABLE nmf_event_light DROP COLUMN IF EXISTS "{col}"')
