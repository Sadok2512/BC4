"""Certified simplified Metrics tree metadata (catalogue 2.68.6)."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TREE_PATH = ROOT / "simple_tree.csv"
LEAVES_PATH = ROOT / "simple_tree_leaves.csv"


@dataclass(frozen=True)
class SimpleKpi:
    tech: str
    theme: str
    kpi: str
    label: str
    families: tuple[str, ...]
    unit: str
    status: str


@dataclass(frozen=True)
class SimpleLeaf:
    simple_name: str
    metric_id: str
    tech: str
    kpi: str


@lru_cache(maxsize=1)
def load_simple_tree() -> tuple[SimpleKpi, ...]:
    with TREE_PATH.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        expected = ["tech", "theme", "kpi", "libelle", "familles_metric_id", "unite", "statut"]
        if reader.fieldnames != expected:
            raise RuntimeError(f"simple_tree.csv header={reader.fieldnames!r}, expected={expected!r}")
        rows = tuple(
            SimpleKpi(
                tech=(row["tech"] or "").strip(),
                theme=(row["theme"] or "").strip(),
                kpi=(row["kpi"] or "").strip(),
                label=(row["libelle"] or "").strip(),
                families=tuple(x for x in (row["familles_metric_id"] or "").split("|") if x),
                unit=(row["unite"] or "").strip(),
                status=(row["statut"] or "").strip(),
            )
            for row in reader
        )
    if len(rows) != 71:
        raise RuntimeError(f"simple_tree.csv rows={len(rows)}, expected=71")
    if any(not all((row.tech, row.theme, row.kpi, row.label, row.status)) for row in rows):
        raise RuntimeError("simple_tree.csv contains an incomplete row")
    return rows


@lru_cache(maxsize=1)
def load_simple_leaves() -> dict[str, SimpleLeaf]:
    with LEAVES_PATH.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        expected = ["simple_name", "metric_id", "tech", "kpi"]
        if reader.fieldnames != expected:
            raise RuntimeError(
                f"simple_tree_leaves.csv header={reader.fieldnames!r}, expected={expected!r}"
            )
        rows = tuple(SimpleLeaf(**{key: (row[key] or "").strip() for key in expected}) for row in reader)
    if any(not all(asdict(row).values()) for row in rows):
        raise RuntimeError("simple_tree_leaves.csv contains an incomplete row")
    by_name = {row.simple_name: row for row in rows}
    if len(by_name) != len(rows):
        raise RuntimeError("simple_tree_leaves.csv contains duplicate simple_name")
    by_metric = {row.metric_id: row for row in rows}
    if len(by_metric) != len(rows):
        raise RuntimeError("simple_tree_leaves.csv contains duplicate metric_id")
    definitions = {(row.tech, row.kpi): row for row in load_simple_tree()}
    invalid_family = [
        row
        for row in rows
        if row.metric_id.split("@", 1)[0]
        not in definitions[(row.tech, row.kpi)].families
    ]
    if invalid_family:
        raise RuntimeError(
            "simple_tree_leaves.csv contains a leaf outside its metric_id family: "
            f"{invalid_family[:3]!r}"
        )
    return by_metric


def apply_simple_metadata(node: dict) -> None:
    if node.get("node_type") != "leaf":
        return
    lookup = load_simple_leaves()
    candidates = (
        node.get("metric_id"),
        node.get("canonical_metric_id"),
        node.get("selection"),
        node.get("display_code"),
    )
    match = next(
        (
            lookup.get(str(candidate).split("!", 1)[0])
            for candidate in candidates
            if candidate
            and lookup.get(str(candidate).split("!", 1)[0]) is not None
        ),
        None,
    )
    if match is None:
        return
    kpi = next(
        row for row in load_simple_tree()
        if row.tech == match.tech and row.kpi == match.kpi
    )
    node["simple_name"] = match.simple_name
    # Presentation technology is certified by the simplified-tree reference.
    # It may differ from the decoder transport technology (notably EN-DC
    # measurements decoded from an LTE signalling record but displayed in NR).
    node["simple_tech"] = match.tech
    node["simple_theme"] = kpi.theme
    node["simple_kpi"] = kpi.kpi
    node["simple_label"] = kpi.label
    node["simple_status"] = kpi.status


def simple_tree_payload() -> list[dict]:
    return [
        {
            "tech": row.tech,
            "theme": row.theme,
            "kpi": row.kpi,
            "label": row.label,
            "families": list(row.families),
            "unit": row.unit,
            "status": row.status,
        }
        for row in load_simple_tree()
    ]
