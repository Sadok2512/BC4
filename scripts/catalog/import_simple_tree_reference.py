"""Import the certified SIMPLE array from Sadok's bc4_tree_exact.html.

The HTML embeds JSON literals (not executable JavaScript) for the simplified
tree.  This importer writes deterministic semicolon-delimited source files;
runtime code never reads the HTML and never classifies by translated labels.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _simple_rows(path: Path) -> list[list]:
    source = path.read_text(encoding="utf-8")
    marker = "const SIMPLE="
    start = source.find(marker)
    if start < 0:
        raise ValueError("const SIMPLE absent")
    start += len(marker)
    end = source.find(";", start)
    if end < 0:
        raise ValueError("terminateur SIMPLE absent")
    rows = json.loads(source[start:end])
    if len(rows) != 66:
        raise ValueError(f"SIMPLE rows={len(rows)}, expected=66")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--out", type=Path, default=Path("app/kpi/simple_tree.csv"))
    parser.add_argument(
        "--leaves-out", type=Path, default=Path("app/kpi/simple_tree_leaves.csv")
    )
    args = parser.parse_args()
    rows = _simple_rows(args.reference)

    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(
            ["tech", "theme", "kpi", "libelle", "familles_metric_id", "unite", "statut"]
        )
        for tech, theme, kpi, label, unit, note, status, leaves in rows:
            families = list(dict.fromkeys(leaf[1].split("@", 1)[0] for leaf in leaves))
            # The two requested derived KPIs close their reference OPEN rows.
            if kpi == "THP_DL_CA_TOTAL":
                families = ["lte_thp_dl_ca_total"]
                status = "ok"
            elif kpi == "CA_NB_SCELLS":
                families = ["lte_ca_nb_scells"]
                status = "ok"
            writer.writerow([tech, theme, kpi, label, "|".join(families), unit, status])

    with args.leaves_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(["simple_name", "metric_id", "tech", "kpi"])
        for tech, _theme, kpi, _label, _unit, _note, _status, leaves in rows:
            for simple_name, metric_id, *_rest in leaves:
                writer.writerow([simple_name, metric_id, tech, kpi])
        writer.writerow(["LTE_THP_DL_CA_TOTAL", "lte_thp_dl_ca_total", "LTE", "THP_DL_CA_TOTAL"])
        writer.writerow(["LTE_CA_NB_SCELLS", "lte_ca_nb_scells", "LTE", "CA_NB_SCELLS"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
