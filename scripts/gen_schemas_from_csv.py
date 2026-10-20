"""Décodeur 1.1.0 — Génération baseline des YAML événements depuis NFF 2.19.

Lit les deux CSV spec (``specs/nmf_all_events_lte_fields_2.19.csv`` et
``specs/nmf_events_coverage.csv``) et émet un YAML par événement
documenté qui n'a PAS déjà de schéma hand-crafted sous
``app/nmf_decoder/schemas/``. Les 19 YAMLs existants ne sont **jamais**
réécrits — ils ont été validés en 1.0.0 et portent du savoir métier
(dimension, weight, groups raffinés) que le CSV plat ne porte pas.

Principes de prudence (règles n°1 et n°5 BC4) :

- ``metric: false`` et ``agg: null`` par défaut sur chaque nouveau champ
  — un YAML baseline ne doit **jamais** apparaître dans ``metric_catalog``
  tant qu'il n'a pas été qualifié manuellement. Un KPI chargé depuis
  une agrégation incorrecte serait une fabrication (règle n°1).
- ``inactive: true`` + ``inactive_reason`` sur chaque nouveau YAML tant
  que la validation live (phase P1) n'a pas été exécutée.
- Headers ``#EI`` / ``#SI`` / ``#DN`` : chaque champ reçoit
  ``redact: true`` — identité abonné / terminal / série, jamais exposés
  dans l'API.
- Détection minimale de groupes : si deux champs successifs sont
  ``#X sets`` + ``#Params/X`` (ou variante), tous les champs suivants
  jusqu'au prochain marqueur ``#`` sont rassemblés dans un groupe ``X``.
  La restitution précise (``start: previous_end``, ``weight: ...``) est
  renvoyée en phase P2 (lecture du txt NFF par événement).

Sortie : {len(missing)} fichiers dans ``app/nmf_decoder/schemas/``.
Idempotent (relancer ne touche pas les YAMLs existants).
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path


SPECS_DIR = Path("/home/devmat/BC4/specs")
# Les YAMLs générés sont **isolés** dans ``schemas-pending/`` pour ne
# pas être chargés par ``schema.schemas()`` tant que la migration DB
# correspondante (P3) n'a pas été appliquée. Les 19 YAMLs hand-crafted
# (1.0.0) restent dans ``schemas/`` et pilotent la production.
LIVE_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "app" / "nmf_decoder" / "schemas"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "app" / "nmf_decoder" / "schemas-pending"
SCHEMAS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_code(prefix: str, name: str) -> str:
    """Normalise ``name`` en snake_case prefixé par l'event lower-case."""
    base = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return f"{prefix}.{base}" if base else prefix


def _type_from_csv(raw: str | None) -> str:
    r = (raw or "").strip().lower()
    if r.startswith("float"):
        return "float"
    if r.startswith("int"):
        return "int"
    if r.startswith("str"):
        return "str"
    return "str"


def _parse_range(raw: str | None) -> list[float | int | None] | None:
    """Extrait [min, max] ou [min, None] depuis les notations du CSV."""
    r = (raw or "").strip()
    if not r:
        return None
    # "0 – 100" / "0-100" / "0 - 100"
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*[-–—]\s*(-?\d+(?:\.\d+)?)$", r)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return [int(a) if a.is_integer() else a, int(b) if b.is_integer() else b]
    # ">= 0" / ">=0" / "≥ 0"
    m = re.match(r"^[>≥]=?\s*(-?\d+(?:\.\d+)?)$", r)
    if m:
        a = float(m.group(1))
        return [int(a) if a.is_integer() else a, None]
    return None


def _unit_norm(raw: str | None) -> str | None:
    u = (raw or "").strip()
    return u or None


def _should_redact(event: str) -> bool:
    """Headers d'identité abonné / terminal / série — jamais exposés."""
    return event.upper() in {"#EI", "#SI", "#DN", "#MF", "#PRODUCT", "#SW", "#HW", "#HASH"}


_MARKER_EVENTS = frozenset({
    "RRA", "RRC", "RRD", "GAA", "GAC", "GAD", "PBA", "PBC", "PBD",
    "CREL", "MEI", "NLIST", "SEI", "ROAM", "LOCK", "MARK", "PCHI",
    "AQRX", "AQI", "VOIPI", "HOI", "RACHI", "L3SM",
})


def _is_marker(event: str) -> bool:
    return event.upper() in _MARKER_EVENTS


# ---------------------------------------------------------------------------
# Group detection
# ---------------------------------------------------------------------------


_SETS_RE = re.compile(r"#\s*(?P<name>[A-Za-z_]+)\s*sets?\b", re.IGNORECASE)
_PARAMS_RE = re.compile(r"#\s*Params?/\s*(?P<name>[A-Za-z_]+)\b", re.IGNORECASE)


def _detect_groups(fields: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sépare les champs en (header, groups).

    Heuristique minimale : un marqueur ``#X sets`` suivi de ``#Params/X``
    délimite un groupe nommé X. Les champs qui suivent (jusqu'au
    prochain marqueur ou fin) sont les champs du groupe. Le reste va
    dans ``header``.

    La vérité fine (start: previous_end, weight: …) est à écrire en P2.
    """
    header: list[dict] = []
    groups: list[dict] = []
    i = 0
    while i < len(fields):
        label = fields[i].get("label", "")
        m_sets = _SETS_RE.search(label)
        if m_sets and i + 1 < len(fields):
            m_params = _PARAMS_RE.search(fields[i + 1].get("label", ""))
            if m_params:
                group_name = m_sets.group("name").lower()
                # Les champs du groupe suivent jusqu'au prochain "#X sets"
                j = i + 2
                group_fields: list[dict] = []
                while j < len(fields):
                    next_label = fields[j].get("label", "")
                    if _SETS_RE.search(next_label):
                        break
                    group_fields.append(fields[j])
                    j += 1
                groups.append({"name": group_name, "fields": group_fields})
                i = j
                continue
        header.append(fields[i])
        i += 1
    return header, groups


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def _emit_field(event: str, prefix: str, csv_field: dict, redact: bool) -> dict:
    name = csv_field["name"]
    code = _norm_code(prefix, name)
    out: dict = {
        "code": code,
        "label": name,
        "type": _type_from_csv(csv_field.get("type")),
        "unit": _unit_norm(csv_field.get("unit")),
        "proof": f"NFF 2.19 {event} {csv_field.get('section', '').strip()} #{csv_field['field_no']}",
        "agg": None,
        "metric": False,
    }
    rng = _parse_range(csv_field.get("range"))
    if rng is not None:
        out["range"] = rng
    if redact:
        out["redact"] = True
    return out


def _emit_yaml(event: str, csv_rows: list[dict], systems: list[int]) -> dict:
    prefix = event.lower().lstrip("#") or event.lower()
    redact = _should_redact(event)

    # Section "Parameters" = header global (Measured sys. + indicateurs)
    # Section "Parameters for LTE…" = corps LTE spécifique
    param_rows = [r for r in csv_rows if r.get("section", "").strip() == "Parameters"]
    lte_rows = [r for r in csv_rows if "Parameters for LTE" in r.get("section", "")]

    all_fields: list[dict] = []
    # Measured sys. va toujours en col 4 (convention existante)
    sys_col = 4
    header_block: list[dict] = []
    for i, r in enumerate(param_rows):
        f = _emit_field(event, prefix, r, redact)
        f["col"] = sys_col + i  # 4, 5, 6…
        header_block.append(f)

    for i, r in enumerate(lte_rows):
        f = _emit_field(event, prefix, r, redact)
        f["col"] = sys_col + len(param_rows) + i
        all_fields.append(f)

    header_lte, groups = _detect_groups(all_fields)

    schema: dict = {
        "event": event,
        "systems": systems,
        "system_col": sys_col,
        "min_format": "2.19",
        "schema_version": "1.1.0",
        "unknown_tail": "keep",
        "generated_from": "specs/nmf_all_events_lte_fields_2.19.csv",
        "inactive": True,
        "inactive_reason": "baseline généré en 1.1.0 ; agg/metric/group raffinements P2",
        "header": header_block + header_lte,
    }
    if groups:
        schema["groups"] = [
            {
                "name": g["name"],
                "fields": g["fields"],
                "start": "previous_end",
                "count_code": f"{prefix}.n_{g['name']}",
                "params_code": f"{prefix}.params_{g['name']}",
                "proof": f"NFF 2.19 {event} LTE #{g['name']} count / params (baseline, P2 raffine)",
            }
            for g in groups
        ]
    if _is_marker(event):
        schema["marker"] = True  # P2 l'exposera dans /captures/{id}/events
    return schema


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    fields_csv = SPECS_DIR / "nmf_all_events_lte_fields_2.19.csv"
    cov_csv = SPECS_DIR / "nmf_events_coverage.csv"
    if not fields_csv.exists() or not cov_csv.exists():
        raise SystemExit(f"Spec manquante : {fields_csv} ou {cov_csv}")

    cov = {r["event"]: r for r in csv.DictReader(cov_csv.open())}
    documented = sorted(e for e, r in cov.items() if r["documented_2.19"] == "doc")

    rows_by_event: dict[str, list[dict]] = {}
    for r in csv.DictReader(fields_csv.open()):
        rows_by_event.setdefault(r["event"], []).append(r)

    existing_live = {f[:-5] for f in os.listdir(LIVE_SCHEMAS_DIR) if f.endswith(".yaml")}
    existing_pending = {f[:-5] for f in os.listdir(SCHEMAS_DIR) if f.endswith(".yaml")}
    existing = existing_live | existing_pending
    missing = [e for e in documented if e not in existing]

    created: list[str] = []
    skipped_no_fields: list[str] = []

    for event in missing:
        csv_rows = rows_by_event.get(event, [])
        if not csv_rows:
            skipped_no_fields.append(event)
            continue
        # Système : 7 pour LTE (convention actuelle). Les events communs
        # (DRATE, AQDL…) sont déjà dans existing ; les nouveaux sont LTE.
        schema = _emit_yaml(event, csv_rows, [7])
        out = SCHEMAS_DIR / f"{event}.yaml"
        out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created.append(event)

    print(f"Documentés   : {len(documented)}")
    print(f"Existants    : {len(existing)}")
    print(f"Créés (nouvelle 1.1.0) : {len(created)}")
    for e in created:
        print(f"  + {e}")
    if skipped_no_fields:
        print(f"Documentés sans champs CSV (sautés) : {skipped_no_fields}")


if __name__ == "__main__":
    main()
