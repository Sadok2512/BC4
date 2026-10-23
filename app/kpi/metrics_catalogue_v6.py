"""Versioned presentation tree for the Metrics workspace.

The labels and hierarchy are copied from the approved v6 HTML.  Runtime code
only binds a catalogue node to a decoder field when the event/field reference
is unambiguous.  Missing bindings remain visible and unavailable.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text

from app.nmf_decoder.schema import fields, offsets

CELLS = (
    ("pcell", "PCell", 0),
    ("scell1", "SCell1", 1),
    ("scell2", "SCell2", 2),
    ("scell3", "SCell3", 3),
    ("scell4", "SCell4", 4),
    ("pscell", "PSCell", None),
    ("scell_nr", "SCell NR", None),
)

# The v6 source numbers for CELLMEAS/MIMOMEAS are physical positions in the
# record, while decoder proofs number fields inside their repeated group.
EXPLICIT_FIELDS = {
    ("CELLMEAS", 5): "cell_band",
    ("CELLMEAS", 6): "cell_ch",
    ("CELLMEAS", 7): "cell_pci",
    ("CELLMEAS", 8): "cell_rssi",
    ("CELLMEAS", 9): "cell_rsrp",
    ("CELLMEAS", 10): "cell_rsrq",
    ("CELLMEAS", 11): "cell_timing",
    ("CELLMEAS", 12): "cell_pathloss",
    ("MIMOMEAS", 4): "mimo_band",
    ("MIMOMEAS", 5): "mimo_ch",
    ("MIMOMEAS", 6): "mimo_pci",
    ("MIMOMEAS", 7): "mimo_port",
    ("MIMOMEAS", 9): "mimo_rssi_p",
    ("MIMOMEAS", 10): "mimo_rsrq_p",
    ("MIMOMEAS", 11): "mimo_rsrp_p",
    ("MIMOMEAS", 12): "mimo_timing_p",
    ("CI", 2): "ci_rs_snr",
    ("CI", 6): "ci_snr_port",
    ("CI", 7): "ci_port",
    ("TAD", 1): "tad_ta",
}

DERIVED_FIELDS = {
    "Number of neighbours": "neighbor_count",
    "Best neighbour RSRP": "neighbor_best_rsrp",
    "Best neighbour RSRQ": "neighbor_best_rsrq",
    "Active SCells": "n_scell_active",
    "Throughput share carried by SCells": "scell_throughput_share",
}

SOURCE_RE = re.compile(r"\[([^ #\]]+)\s+#(\d+)\]")


@lru_cache(maxsize=1)
def source_tree() -> dict:
    return json.loads((Path(__file__).with_name("metrics_catalogue_v6.json")).read_text())


@lru_cache(maxsize=1)
def field_index() -> dict[tuple[str, int], str]:
    candidates: dict[tuple[str, int], list[str]] = {}
    for column, definition in fields().items():
        proof = definition.get("proof") or ""
        matches = re.findall(r"#(\d+)(?!.*#\d+)", proof)
        if matches:
            candidates.setdefault((definition["event"], int(matches[-1])), []).append(column)
    result = dict(EXPLICIT_FIELDS)
    for key, columns in candidates.items():
        if key not in result and len(columns) == 1:
            result[key] = columns[0]
    return result


def _id(path: list[str]) -> str:
    return "m6_" + hashlib.sha1("\x1f".join(path).encode()).hexdigest()[:16]


def _source(node: dict) -> tuple[str | None, int | None, str | None]:
    match = SOURCE_RE.search(node.get("source") or "")
    if not match:
        return None, None, DERIVED_FIELDS.get(node["label"])
    event, field_idx = match.group(1), int(match.group(2))
    return event, field_idx, field_index().get((event, field_idx))


def _unit(note: str | None) -> str:
    value = (note or "").split(" · ", 1)[0].strip()
    return "" if value in {"", "—"} else value


def catalogue(db, project_id: str, metrics: list[dict]) -> dict:
    from app.kpi.metrics_v3 import definitions

    definitions_by_column = {}
    for code, definition in definitions().items():
        definitions_by_column.setdefault(definition["source_column"], []).append((code, definition))
    metric_counts = {metric["code"]: int(metric["n_in_project"]) for metric in metrics}
    cell_counts = {
        (row.metric_code, row.cell_index): int(row.n)
        for row in db.execute(
            text("""SELECT metric_code,cell_index,count(DISTINCT (capture_id,second)) n
                    FROM nmf_cell_second WHERE project_id=:pid AND value IS NOT NULL
                    GROUP BY metric_code,cell_index"""),
            {"pid": project_id},
        )
    }
    present_events = {row[0] for row in db.execute(
        text("SELECT DISTINCT event_code FROM nmf_event_light WHERE project_id=:pid"),
        {"pid": project_id},
    )}
    event_codes = {"HOA","HOS","HOI","CAA","CAC","CAD","DAA","DAC","DAD","RRA","RRC","RRD",
                   "GAA","GAC","GAD","PBA","PBC","PBD","RACHI","MEI","SEI","SCELLMOD","LOCK","ROAM","MARK"}
    nodes: list[dict] = []

    def visit(node: dict, parent_id: str | None, path: list[str], order: int, inherited=None):
        current_path = [*path, node["label"]]
        node_id = _id(current_path)
        event, field_idx, source_column = _source(node)
        source = (event, field_idx, source_column) if event or source_column else inherited
        is_star_metric = bool(node.get("source") and "★" in node["label"] and len(node["children"]) == 7)
        inherited_cell = None
        if inherited and not node.get("source") and not node["children"]:
            for cell, label, index in CELLS:
                if node["label"].rstrip().endswith("— " + label) or node["label"].rstrip().endswith("—" + label):
                    inherited_cell = (cell, index)
                    break
        effective = source or (None, None, None)
        event, field_idx, source_column = effective
        candidates = definitions_by_column.get(source_column, []) if source_column else []
        exact = [candidate for candidate in candidates if candidate[0] == source_column]
        base_code, definition = exact[0] if len(exact) == 1 else candidates[0] if len(candidates) == 1 else (None, None)
        cell = inherited_cell[0] if inherited_cell else None
        cell_index = inherited_cell[1] if inherited_cell else None
        is_terminal = not node["children"]
        selectable = bool(is_terminal and base_code)
        proof = "documented"
        reason = None
        if cell in {"pscell", "scell_nr"}:
            proof = "open"
            selectable = False
            reason = "P4 proof pending"
        elif source_column in {"cell_band", "cell_ch", "cell_pci", "cell_rssi", "cell_rsrp", "cell_rsrq", "cell_timing", "cell_pathloss"}:
            proof = "content" if cell and cell != "pcell" else "documented"
        elif event == "TXPC" and cell is not None:
            proof = "content"
        elif source_column and not base_code:
            proof = "open"
            reason = "Decoder field is not exposed as a metric"
        elif is_terminal and not source_column:
            proof = "open"
            reason = "No proven decoder field binding"
        selection = None
        n = 0
        if selectable and definition:
            if cell is not None:
                selection = f"{base_code}@{cell_index}" if cell_index is not None else None
                n = cell_counts.get((source_column, cell_index), 0) if cell_index is not None else 0
                selectable = selection is not None and n > 0
                if n == 0:
                    reason = "cell_absent"
            else:
                selection = base_code
                # Non-cell counts are retained from the existing, proven projection.
                n = metric_counts.get(base_code, 0)
                selectable = n > 0
                if n == 0:
                    reason = "absent_in_capture" if event and event not in present_events else "field_empty"
        nodes.append(
            dict(
                node_id=node_id,
                parent_id=parent_id,
                order=order,
                label=node["label"],
                note=node.get("note"),
                source=node.get("source"),
                node_type="category" if parent_id is None else "metric" if is_star_metric else "leaf" if is_terminal else "group",
                metric_id=(f"{base_code}@{cell}" if base_code and cell else base_code),
                selection=selection,
                event=event,
                field_idx=field_idx,
                system_col=offsets(event).get('system_col') if event else None,
                first_param_col=offsets(event).get('first_param_col') if event else None,
                source_column=source_column,
                unit=_unit(node.get("note")),
                cell=cell,
                n=n,
                proof=proof,
                selectable=selectable,
                reason=reason,
                count_semantics="occurrences" if event in event_codes else "distinct capture-seconds with non-NULL value",
            )
        )
        for child_order, child in enumerate(node["children"]):
            visit(child, node_id, current_path, child_order, effective if is_star_metric else None)

    for order, root in enumerate(source_tree()["tree"]):
        visit(root, None, [], order)
    return {
        "catalogue_version": "v6",
        "title": source_tree()["title"],
        "header": source_tree()["header"],
        "nodes": nodes,
    }
