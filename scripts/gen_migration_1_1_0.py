"""Génère la migration alembic 0035 pour promouvoir le décodeur 1.1.0.

Compare les champs présents dans ``schemas/`` + ``schemas-pending/``
(hors ``needs_refinement``) avec ceux déjà matérialisés dans
``nmf_event_deep`` / ``nmf_event_light`` par la migration 0031 et
émet :

- ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` pour chaque nouveau champ.
  Les tables sont partitionnées : l'ajout parent propage aux partitions.
  Pas de ``DEFAULT`` → l'ajout est instantané en PostgreSQL ≥ 11.
- Recréation de la ``VIEW nmf_metric_value`` incluant tous les champs
  (anciens + nouveaux) sous le même pattern UNION ALL (deep + group +
  light).

Produit un fichier Python prêt à être placé dans ``alembic/versions/``.
"""
from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "app" / "nmf_decoder" / "schemas"
PENDING = REPO / "app" / "nmf_decoder" / "schemas-pending"
MIG_PATH = REPO / "alembic" / "versions" / "0035_nmf_decoder_1_1_0.py"


def _type_sql(type_hint: str, deep: bool) -> str:
    """Type colonne SQL : deep garde bigint/double precision ; light=double precision uniforme."""
    if not deep:
        return "double precision"
    t = (type_hint or "").lower()
    if t.startswith("float"):
        return "double precision"
    if t.startswith("int"):
        return "bigint"
    return "double precision"


def _collect_fields(dirs: list[Path], require_promotable: bool) -> tuple[dict[str, str], dict[str, str]]:
    """Retourne (headers, groups) → mapping ``column -> sql_type_hint``."""
    headers: dict[str, str] = {}
    groups: dict[str, str] = {}
    for d in dirs:
        for p in d.glob("*.yaml"):
            schema = json.loads(p.read_text(encoding="utf-8"))
            if require_promotable and schema.get("needs_refinement"):
                continue
            for f in schema.get("header", []) or []:
                headers[f["code"].replace(".", "_")] = f.get("type", "")
            for g in schema.get("groups", []) or []:
                for f in g.get("fields", []) or []:
                    groups[f["code"].replace(".", "_")] = f.get("type", "")
    return headers, groups


def main() -> None:
    # Vérité DB actuelle : colonnes présentes dans nmf_event_deep /
    # nmf_event_group après la migration 0031. On compare contre l'union
    # schemas/ + schemas-pending/ (hors needs_refinement) pour trouver
    # les colonnes manquantes à ajouter.
    import subprocess
    def _db_columns(table: str) -> set[str]:
        out = subprocess.check_output([
            "docker", "exec", "bc4-db-1", "psql", "-U", "bc4", "-t", "-A",
            "-c", f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
        ], text=True)
        return {c.strip() for c in out.splitlines() if c.strip()}

    # Colonnes de méta-base (clé primaire + typage/trace) exclues de la
    # VIEW nmf_metric_value : elles ne sont pas des valeurs métrique
    # (string, tableau, timestamp) et planteraient le cast `::double precision`.
    BASE_COLS = {
        "project_id", "capture_id", "seq", "line_no", "event_code", "system",
        "ts", "t_rel_s", "format_version", "decoder_version", "schema_version",
        "decode_status", "reasons", "tokens", "field_codes", "unk_string",
        "quoted", "seq_last", "second", "dimension", "unknown", "n_records",
        "n_partial", "group_name", "set_index", "identity",
    }

    live_h = _db_columns("nmf_event_deep") - BASE_COLS
    live_g = _db_columns("nmf_event_group") - BASE_COLS
    all_h, all_g = _collect_fields([LIVE, PENDING], require_promotable=True)

    new_h = {c: t for c, t in all_h.items() if c not in live_h}
    new_g = {c: t for c, t in all_g.items() if c not in live_g}

    # Columns to ADD.
    adds_deep = [(c, _type_sql(t, deep=True)) for c, t in sorted(new_h.items())]
    adds_group = [(c, _type_sql(t, deep=True)) for c, t in sorted(new_g.items())]
    adds_light = [(c, "double precision") for c in sorted(new_h) + sorted(new_g)]
    adds_light_group = [(c, "double precision") for c in sorted(new_g)]

    # VIEW nmf_metric_value : toutes les colonnes finales (anciennes + nouvelles).
    all_h_final = sorted(set(live_h) | set(all_h))
    all_g_final = sorted(set(live_g) | set(all_g))

    def _view_values(prefix: str, cols: list[str]) -> str:
        return ",".join(f"('{c}',{prefix}.{c}::double precision)" for c in cols)

    deep_values = _view_values("d", all_h_final)
    group_values = _view_values("d", all_g_final)
    light_values = _view_values("d", all_h_final + all_g_final)

    view_sql = f"""CREATE VIEW nmf_metric_value AS
SELECT d.project_id,d.capture_id,d.seq,v.code,v.value,c.decoder_version
 FROM nmf_event_deep d JOIN nmf_capture c USING(project_id,capture_id)
 CROSS JOIN LATERAL (VALUES {deep_values}) v(code,value)
 WHERE c.decode_level='deep' AND v.value IS NOT NULL
UNION ALL
SELECT d.project_id,d.capture_id,d.seq,v.code,v.value,c.decoder_version
 FROM nmf_event_group d JOIN nmf_capture c USING(project_id,capture_id)
 CROSS JOIN LATERAL (VALUES {group_values}) v(code,value)
 WHERE c.decode_level='deep' AND d.set_index=0 AND v.value IS NOT NULL
UNION ALL
SELECT d.project_id,d.capture_id,d.seq,v.code,v.value,c.decoder_version
 FROM nmf_event_light d JOIN nmf_capture c USING(project_id,capture_id)
 CROSS JOIN LATERAL (VALUES {light_values}) v(code,value)
 WHERE c.decode_level='light' AND v.value IS NOT NULL"""

    def _add_block(table: str, adds: list[tuple[str, str]]) -> str:
        if not adds:
            return f"    # {table} : aucune nouvelle colonne"
        lines = [f"    # {len(adds)} nouvelles colonnes dans {table}"]
        for c, t in adds:
            lines.append(f'    op.execute("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {c} {t}")')
        return "\n".join(lines)

    migration = f'''"""nmf_decoder 1.1.0 — ajout {len(adds_deep)} + {len(adds_group)} + {len(adds_light)} + {len(adds_light_group)} colonnes."""
from alembic import op
revision = "0035_nmf_decoder_1_1_0"
down_revision = "0034_kpi_light_context_index"
branch_labels = depends_on = None

# Généré par scripts/gen_migration_1_1_0.py depuis les YAMLs
# schemas/ + schemas-pending/ (hors needs_refinement).
#
# ``ADD COLUMN IF NOT EXISTS`` sur PostgreSQL ≥ 11 est instantané si
# pas de DEFAULT (métadata-only). Les tables sont partitionnées ;
# l'ADD parent propage automatiquement aux partitions existantes.


def upgrade():
{_add_block("nmf_event_deep", adds_deep)}
{_add_block("nmf_event_group", adds_group)}
{_add_block("nmf_event_light", adds_light)}
{_add_block("nmf_event_light_group", adds_light_group)}
    op.execute("DROP VIEW IF EXISTS nmf_metric_value")
    op.execute("""{view_sql}""")


def downgrade():
    op.execute("DROP VIEW IF EXISTS nmf_metric_value")
    # Ré-exécuter 0031 pour recréer la vue originale est hors scope ici :
    # la downgrade retire la vue mais conserve les colonnes ajoutées
    # (pas de DROP COLUMN pour éviter la perte de données décodées en 1.1.0).
'''

    MIG_PATH.write_text(migration, encoding="utf-8")
    print(f"wrote {MIG_PATH}")
    print(f"  deep        : +{len(adds_deep)}")
    print(f"  group       : +{len(adds_group)}")
    print(f"  light       : +{len(adds_light)}")
    print(f"  light_group : +{len(adds_light_group)}")
    print(f"  VIEW total  : {len(all_h_final) + len(all_g_final)} champs")


if __name__ == "__main__":
    main()
