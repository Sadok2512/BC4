"""Per-file project summary, derived only from capture-local canonical events."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable


EVENTS = {
    "CMDREQ", "CMDCOMP", "DCOMP", "DAF", "DRATE",
    "PDCPRATED", "PDCPRATEU", "RLCRATE", "RLCRATEU",
    "AQDL", "RTT", "RACHI", "CAA", "CAF", "CAD", "DAA",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _field(fields: dict[str, Any], csv_column: int) -> Any:
    """raw_fields cN is CSV column N+1 (event and timestamp precede it)."""
    return fields.get(f"c{csv_column - 1}")


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    task: str


def _task(action: str) -> str | None:
    if action.startswith("StartHTTP"):
        return "HTTP_UL" if action in {"StartHTTPUL", "StartHTTPUpload"} else "HTTP_DL"
    if action in {"VoiceCallStart", "ReceiveCallStart"}:
        return "VOICE"
    if action == "StartPing" or action.startswith("StartPing"):
        return "PING"
    return None


def _windows(rows: list[dict[str, Any]]) -> tuple[list[Window], set[str]]:
    starts = [(index, row, _task(str(row["raw_fields"].get("service_action") or "")))
              for index, row in enumerate(rows) if row["event_code"] == "CMDREQ"]
    starts = [(index, row, task) for index, row, task in starts if task]
    labels = {task for _, _, task in starts if task}
    windows: list[Window] = []
    for pos, (index, start, task) in enumerate(starts):
        boundary = starts[pos + 1][1]["seq"] if pos + 1 < len(starts) else 2**31 - 1
        terminal_codes = {"DCOMP", "DAF"} if task in {"HTTP_DL", "HTTP_UL", "PING"} else {"CAD", "CAF"}
        terminal = next((row for row in rows[index + 1:]
                         if row["seq"] < boundary and row["event_code"] in terminal_codes), None)
        if terminal is None:
            continue
        end = next((row for row in rows[index + 1:]
                    if terminal["seq"] < row["seq"] < boundary and row["event_code"] == "CMDCOMP"), None)
        if end is not None:
            windows.append(Window(int(start["seq"]), int(end["seq"]), str(task)))
    return windows, labels


def _inside(seq: int, windows: Iterable[Window]) -> bool:
    return any(window.start <= seq <= window.end for window in windows)


def _rate_cell(values: list[float], source: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "value": mean(values) / 1_000_000 if values else None,
        "n": len(values) if values else None,
        "max": max(values) / 1_000_000 if values else None,
        "unit": "Mbit/s",
        "source_event": source,
        "reason": None if values else reason or f"no {source} in file",
    }


def _count_cell(numerator: int, denominator: int, source: str, attempt: str) -> dict[str, Any]:
    available = denominator > 0
    return {
        "value": numerator if available else None,
        "n": denominator if available else None,
        "max": None,
        "unit": "count",
        "source_event": source,
        "reason": None if available else f"no {attempt} in file",
    }


def summarize_file(
    file_row: dict[str, Any], events: list[dict[str, Any]], available_events: set[str] | None = None,
) -> dict[str, Any]:
    captures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    kinds: set[str] = set()
    for row in events:
        captures[str(row["capture_id"])].append(row)
        if row.get("kind"):
            kinds.add(str(row["kind"]))

    all_windows: dict[str, list[Window]] = {}
    task_labels: set[str] = set()
    for capture_id, rows in captures.items():
        canonical_rows = [row for row in rows if row.get("seq") is not None]
        canonical_rows.sort(key=lambda row: int(row["seq"]))
        captures[capture_id] = canonical_rows
        windows, labels = _windows(canonical_rows)
        all_windows[capture_id] = windows
        task_labels.update(labels)

    scanner = bool(kinds) and kinds == {"scanner"}
    task_value = "Scanner" if scanner else " + ".join(sorted(task_labels)) or None
    task_n = sum(len(windows) for windows in all_windows.values()) if task_value and not scanner else (len(captures) if scanner else None)

    buckets: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for capture_id, rows in captures.items():
        windows = all_windows.get(capture_id, [])
        if scanner:
            continue
        for row in rows:
            seq = int(row["seq"])
            if not _inside(seq, windows):
                continue
            event = str(row["event_code"])
            fields = row["raw_fields"] or {}
            system = str(row.get("system") or "").upper()
            if event == "DRATE":
                dl = _number(_field(fields, 7))
                ul = _number(_field(fields, 6))
                if dl is not None:
                    buckets["dl_total"].append(dl)
                if ul is not None:
                    buckets["ul_total"].append(ul)
            elif event in {"PDCPRATED", "RLCRATE"}:
                value = _number(_field(fields, 6))
                if value is not None and system in {"LTE", "NR"}:
                    # PDCP is the canonical split. RLC is retained only as a
                    # fallback when this file has no PDCP sample for the system.
                    buckets[f"{event.lower()}_{system.lower()}"].append(value)
            elif event in {"PDCPRATEU", "RLCRATEU"}:
                value = _number(_field(fields, 6))
                if value is not None and system in {"LTE", "NR"}:
                    buckets[f"{event.lower()}_{system.lower()}"].append(value)
            elif event == "AQDL":
                value = _number(_field(fields, 5))
                if value is not None:
                    buckets["mos"].append(value)
            elif event == "RTT":
                value = _number(_field(fields, 4))
                if value is not None:
                    buckets["latency"].append(value)
            elif event == "RACHI":
                preambles = _number(_field(fields, 9))
                preamble_failures = _number(_field(fields, 10))
                contention_failures = _number(_field(fields, 12))
                if preambles is not None:
                    counts["rach_attempt"] += int(preambles)
                    counts["rach_fail"] += int(preamble_failures or 0) + int(contention_failures or 0)
            elif event in {"CAA", "CAF", "CAD", "DAA", "DAF"}:
                counts[event] += 1

    def split(direction: str, system: str) -> dict[str, Any]:
        pdcp = buckets.get(f"pdcp{'rated' if direction == 'dl' else 'rateu'}_{system}", [])
        rlc = buckets.get(f"rlc{'rate' if direction == 'dl' else 'rateu'}_{system}", [])
        source = "PDCPRATED" if direction == "dl" else "PDCPRATEU"
        if pdcp:
            return _rate_cell(pdcp, source)
        rlc_source = "RLCRATE" if direction == "dl" else "RLCRATEU"
        return _rate_cell(rlc, rlc_source, f"no {source}/{rlc_source} {system.upper()} in file")

    mos = buckets.get("mos", [])
    latency = buckets.get("latency", [])
    cells = {
        "task": {"value": task_value, "n": task_n, "max": None, "unit": None,
                 "source_event": "CMDREQ/CMDCOMP", "reason": None if task_value else "no supported command in file"},
        "dl_total": _rate_cell(buckets.get("dl_total", []), "DRATE"),
        "dl_lte": split("dl", "lte"),
        "dl_nr": split("dl", "nr"),
        "ul_total": _rate_cell(buckets.get("ul_total", []), "DRATE"),
        "ul_lte": split("ul", "lte"),
        "ul_nr": split("ul", "nr"),
        "mos": {"value": mean(mos) if mos else None, "n": len(mos) if mos else None,
                "max": max(mos) if mos else None, "unit": "MOS", "source_event": "AQDL",
                "reason": None if mos else "no AQDL in file"},
        "rach_fail": _count_cell(counts["rach_fail"], counts["rach_attempt"], "RACHI", "RACHI"),
        "call_setup_fail": _count_cell(counts["CAF"], counts["CAA"], "CAF", "CAA"),
        "voice_drop": _count_cell(counts["CAD"], counts["CAA"], "CAD", "CAA"),
        "session_fail": _count_cell(counts["DAF"], counts["DAA"], "DAF", "DAA"),
        "latency": {"value": mean(latency) if latency else None, "n": len(latency) if latency else None,
                    "max": max(latency) if latency else None, "unit": "ms", "source_event": "RTT",
                    "reason": None if latency else "no RTT in file"},
    }
    if scanner:
        for key, cell in cells.items():
            if key != "task":
                cell.update(value=None, n=None, max=None, reason="scanner capture")
    for key, source in {"call_setup_fail": "CAF", "latency": "RTT"}.items():
        if available_events is not None and source not in available_events:
            cells[key].update(value=None, n=None, max=None, reason=f"no {source} in file")
    return {"file_id": file_row["id"], "filename": file_row["filename"], "cells": cells}
