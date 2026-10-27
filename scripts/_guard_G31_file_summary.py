#!/usr/bin/env python3
"""G31: compare live /files/summary with the persisted source NMF files."""
from __future__ import annotations

import csv
import json
import math
import os
import urllib.request

from sqlalchemy import text

from app.db import SessionLocal

PID = "4b7bfd50ddb6"
WITNESSES = {
    "http": "44621571bccc",
    "voice": "e84832b42679",
    "scanner": "289784700e72",
}


def api(path: str):
    request = urllib.request.Request(os.environ.get("BC4_API_URL", "http://localhost:8000") + path)
    request.add_header("Authorization", "Bearer " + os.environ["BC4_TOKEN"])
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def rows(path: str):
    with open(path, newline="", encoding="utf-8", errors="replace") as source:
        yield from csv.reader(source)


def truth(path: str):
    active_http = terminal_http = False
    active_voice = terminal_voice = False
    drate: list[float] = []
    counts = {code: 0 for code in ("DAA", "DAF", "CAA", "CAF", "CAD")}
    for fields in rows(path):
        if not fields or fields[0].startswith("#"):
            continue
        event = fields[0]
        action = fields[4] if event == "CMDREQ" and len(fields) > 4 else ""
        if action.startswith("StartHTTP"):
            active_http, terminal_http = True, False
        elif action in {"VoiceCallStart", "ReceiveCallStart"}:
            active_voice, terminal_voice = True, False
        if active_http:
            if event == "DRATE" and len(fields) > 6 and fields[6]:
                drate.append(float(fields[6]))
            if event in {"DAA", "DAF"}:
                counts[event] += 1
            if event in {"DCOMP", "DAF"}:
                terminal_http = True
            elif event == "CMDCOMP" and terminal_http:
                active_http = terminal_http = False
        if active_voice:
            if event in {"CAA", "CAF", "CAD"}:
                counts[event] += 1
            if event in {"CAF", "CAD"}:
                terminal_voice = True
            elif event == "CMDCOMP" and terminal_voice:
                active_voice = terminal_voice = False
    return {"dl_total": sum(drate) / len(drate) / 1e6 if drate else None,
            "dl_n": len(drate), **counts}


def main():
    with SessionLocal() as db:
        witnesses = {row.capture_id: dict(row._mapping) for row in db.execute(text("""
            SELECT c.capture_id,c.kind,f.filename,f.source_path
            FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
            WHERE c.project_id=:pid AND c.capture_id=ANY(:captures)
        """), {"pid": PID, "captures": list(WITNESSES.values())})}
    payloads = [api(f"/projects/{PID}/files/summary?offset={offset}&limit=50") for offset in (0, 50)]
    summaries = {row["filename"]: row for payload in payloads for row in payload["files"]}
    failed = False
    for label, capture_id in WITNESSES.items():
        witness = witnesses[capture_id]
        source = truth(witness["source_path"])
        summary = summaries[witness["filename"]]
        cells = summary["cells"]
        print(f"[{label}] capture={capture_id} file={witness['filename']}")
        print(" source", json.dumps(source, sort_keys=True))
        if label == "http":
            match = math.isclose(cells["dl_total"]["value"], source["dl_total"], rel_tol=0, abs_tol=1e-12)
            match &= cells["dl_total"]["n"] == source["dl_n"]
            match &= cells["session_fail"]["value"] == source["DAF"]
            match &= cells["session_fail"]["n"] == source["DAA"]
        elif label == "voice":
            match = cells["call_setup_fail"]["value"] is None and source["CAF"] == 0
            match &= cells["voice_drop"]["value"] == source["CAD"]
            match &= cells["voice_drop"]["n"] == source["CAA"]
        else:
            match = cells["task"]["value"] == "Scanner"
            match &= all(cell["value"] is None for key, cell in cells.items() if key != "task")
        print(" api", json.dumps(cells, sort_keys=True))
        print(" PASS" if match else " FAIL")
        failed |= not match
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

