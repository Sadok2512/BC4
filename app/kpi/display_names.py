"""Certified display names for the Metrics catalogue.

The CSV is presentation metadata only. ``metric_id_actuel`` is matched to
the baked ``display_code`` emitted by the catalogue builder; selectors and
technical metric ids remain unchanged.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DISPLAY_NAMES_PATH = Path(__file__).with_name("display_names.csv")
EXPECTED_ROWS = 4304


@dataclass(frozen=True)
class DisplayName:
    metric_id: str
    display_code: str
    short_name: str
    branch: str


@lru_cache(maxsize=1)
def load_display_names() -> dict[str, DisplayName]:
    """Load and strictly validate the supplied semicolon-delimited mapping."""
    with DISPLAY_NAMES_PATH.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        expected_header = [
            "metric_id_actuel",
            "display_code_lisible",
            "nom_court",
            "branche",
        ]
        if reader.fieldnames != expected_header:
            raise RuntimeError(
                f"display_names.csv header={reader.fieldnames!r}, expected={expected_header!r}"
            )
        rows = [
            DisplayName(
                metric_id=(row["metric_id_actuel"] or "").strip(),
                display_code=(row["display_code_lisible"] or "").strip(),
                short_name=(row["nom_court"] or "").strip(),
                branch=(row["branche"] or "").strip(),
            )
            for row in reader
        ]

    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"display_names.csv rows={len(rows)}, expected={EXPECTED_ROWS}")
    empty = [row for row in rows if not all(row.__dict__.values())]
    if empty:
        raise RuntimeError(f"display_names.csv contains empty fields: {empty[:3]!r}")
    by_metric_id = {row.metric_id: row for row in rows}
    if len(by_metric_id) != len(rows):
        raise RuntimeError("display_names.csv contains duplicate metric_id_actuel")
    readable = {row.display_code for row in rows}
    if len(readable) != len(rows):
        raise RuntimeError("display_names.csv contains duplicate display_code_lisible")
    trailing = [
        row.metric_id
        for row in rows
        if row.display_code.endswith("_") or row.short_name.endswith("_")
    ]
    if trailing:
        raise RuntimeError(
            f"display_names.csv contains names ending in underscore: {trailing[:3]!r}"
        )
    return by_metric_id


def apply_display_name(node: dict) -> None:
    """Attach presentation fields without changing the technical identity."""
    if node.get("node_type") != "leaf":
        return
    technical_display_code = node.get("display_code")
    if not technical_display_code:
        return
    display = load_display_names().get(technical_display_code)
    if display is None:
        return
    node["display_code_lisible"] = display.display_code
    node["nom_court"] = display.short_name
    node["display_branch"] = display.branch
