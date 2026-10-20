"""Décodeur 1.1.0 — Validation structurelle et comptage sur TEST2.

Pour chaque YAML sous ``app/nmf_decoder/schemas/`` :

1. **Structurel** : JSON parsable, clés obligatoires (``event``, ``systems``,
   ``system_col``, ``min_format``, ``schema_version``, ``header``), tous
   les champs portent ``code``/``label``/``type``/``proof``, pas de
   doublons de ``code`` au niveau header, groupes bien formés.

2. **Présence** : combien de lignes ``stg_event_raw`` existent sur TEST2
   (``project_id = 134af70a06eb``) pour chaque ``event_code``. Un
   événement sans donnée est marqué « no_data_on_test2 » — baseline
   non vérifiable sur ce projet.

3. **Capacité** : nombre de champs header + groupe — peut-on servir les
   KPI dérivés ?

Produit un rapport markdown à
``decoder-1.1.0-audit/validation-phase1.md`` + un CSV mesurable à
``decoder-1.1.0-audit/validation-phase1.csv``.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LIVE_SCHEMAS_DIR = REPO / "app" / "nmf_decoder" / "schemas"
PENDING_SCHEMAS_DIR = REPO / "app" / "nmf_decoder" / "schemas-pending"
AUDIT_DIR = Path("/home/devmat/BC4/decoder-1.1.0-audit")
AUDIT_DIR.mkdir(exist_ok=True)
TEST2_COUNTS_CSV = AUDIT_DIR / "test2-event-counts.csv"


REQUIRED_KEYS = {"event", "systems", "system_col", "min_format", "schema_version", "header"}
FIELD_KEYS = {"code", "label", "type", "proof"}


def _test2_counts() -> dict[str, int]:
    """Charge le comptage par event_code sur TEST2 depuis le CSV capturé en pré-audit."""
    counts: dict[str, int] = {}
    if not TEST2_COUNTS_CSV.exists():
        return counts
    for line in TEST2_COUNTS_CSV.read_text().splitlines():
        parts = line.split("|")
        if len(parts) == 2 and parts[1].strip().isdigit():
            counts[parts[0].strip()] = int(parts[1])
    return counts


def _structural(schema: dict) -> list[str]:
    issues: list[str] = []
    missing = REQUIRED_KEYS - set(schema)
    if missing:
        issues.append(f"missing_keys={sorted(missing)}")
    for section_name in ("header",):
        for i, f in enumerate(schema.get(section_name, []) or []):
            missing_f = FIELD_KEYS - set(f)
            if missing_f:
                issues.append(f"header[{i}] missing {sorted(missing_f)}")
    for gi, g in enumerate(schema.get("groups", []) or []):
        if not g.get("name") or not isinstance(g.get("fields"), list):
            issues.append(f"group[{gi}] malformed")
            continue
        for fi, f in enumerate(g["fields"] or []):
            missing_f = FIELD_KEYS - set(f)
            if missing_f:
                issues.append(f"groups[{gi}].fields[{fi}] missing {sorted(missing_f)}")
    # Détection codes dupliqués (= baseline à raffiner, pas un bug bloquant)
    all_fields = list(schema.get("header", []) or [])
    for g in schema.get("groups", []) or []:
        all_fields.extend(g.get("fields") or [])
    codes = [f["code"] for f in all_fields if "code" in f]
    dups = sorted({c for c in codes if codes.count(c) > 1})
    if dups:
        issues.append(f"duplicate_codes={dups}")
    return issues


def main() -> None:
    counts = _test2_counts()
    rows: list[dict] = []
    all_schemas = list(LIVE_SCHEMAS_DIR.glob("*.yaml")) + list(PENDING_SCHEMAS_DIR.glob("*.yaml"))
    for path in sorted(all_schemas):
        event = path.stem
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            rows.append({
                "event": event, "status": "FAIL_PARSE", "n_header": 0, "n_groups": 0,
                "n_fields_total": 0, "test2_rows": 0, "inactive": True, "issues": str(e),
            })
            continue
        issues = _structural(schema)
        n_header = len(schema.get("header", []) or [])
        groups = schema.get("groups", []) or []
        n_fields_in_groups = sum(len(g.get("fields") or []) for g in groups)
        test2 = counts.get(event, 0)
        inactive = bool(schema.get("inactive", False))
        if issues and any("missing" in s for s in issues):
            status = "FAIL_STRUCT"
        elif test2 == 0:
            status = "PASS_NO_DATA"
        elif issues:  # ex. duplicate_codes
            status = "PASS_WITH_WARN"
        else:
            status = "PASS"
        rows.append({
            "event": event,
            "status": status,
            "n_header": n_header,
            "n_groups": len(groups),
            "n_fields_total": n_header + n_fields_in_groups,
            "test2_rows": test2,
            "inactive": inactive,
            "issues": "; ".join(issues) if issues else "",
            "generated_from": schema.get("generated_from") or "hand-crafted",
            "marker": bool(schema.get("marker", False)),
        })

    out_csv = AUDIT_DIR / "validation-phase1.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Agrégats
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    hand = [r for r in rows if r["generated_from"] == "hand-crafted"]
    gen = [r for r in rows if r["generated_from"] != "hand-crafted"]
    markers = [r for r in rows if r["marker"]]

    out_md = AUDIT_DIR / "validation-phase1.md"
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# Décodeur 1.1.0 — Validation Phase 1\n\n")
        f.write(f"Total YAML : {len(rows)}\n")
        f.write(f"- hand-crafted (1.0.0) : {len(hand)}\n")
        f.write(f"- générés (1.1.0 baseline) : {len(gen)}\n")
        f.write(f"- markers (signalisation) : {len(markers)}\n\n")
        f.write("## Agrégat par statut\n\n")
        for st in ("PASS", "PASS_WITH_WARN", "PASS_NO_DATA", "FAIL_STRUCT", "FAIL_PARSE"):
            f.write(f"- **{st}** : {by_status.get(st, 0)}\n")
        f.write("\n## Détail\n\n")
        f.write("| event | status | n_header | n_groups | n_fields | TEST2 rows | marker | issues |\n")
        f.write("|-------|--------|---------:|---------:|---------:|-----------:|:------:|--------|\n")
        for r in sorted(rows, key=lambda x: (x["status"], x["event"])):
            f.write(
                f"| {r['event']} | {r['status']} | {r['n_header']} | {r['n_groups']} | "
                f"{r['n_fields_total']} | {r['test2_rows']} | "
                f"{'✓' if r['marker'] else ''} | {r['issues'][:80]} |\n"
            )

    print(f"wrote {out_csv} and {out_md}")
    for st, n in sorted(by_status.items()):
        print(f"  {st:16s} : {n}")


if __name__ == "__main__":
    main()
