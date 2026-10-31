#!/usr/bin/env python3
"""Manual post-deploy harness for G18b, G24, G24b, G32, G51 and G56."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

DEFAULT_PID = "43e81a34a073"
DEFAULT_CAPTURE = "a4b0c321c52e"
G56_PROVEN_CAPTURE = "ecffb18dbd7f"
ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / "scripts" / "guards_2026_10"
VERDICT_RE = re.compile(r"\bVERDICT=(PASS|FAIL)\b")


def _run(name: str, command: list[str]) -> tuple[str, float, int]:
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    duration = time.monotonic() - started
    print(f"\n===== {name} =====")
    print(completed.stdout.rstrip())
    matches = VERDICT_RE.findall(completed.stdout)
    verdict = matches[-1] if matches else "FAIL"
    if completed.returncode != 0 or verdict != "PASS":
        verdict = "FAIL"
    if not matches:
        print(f"{name} VERDICT=FAIL reason=missing_verdict_line")
    return verdict, duration, completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    parser.add_argument("--token", default=os.environ.get("G51_TOKEN"))
    parser.add_argument("--pid", default=DEFAULT_PID)
    parser.add_argument("--capture", default=DEFAULT_CAPTURE)
    args = parser.parse_args(argv)

    if not os.environ.get("BC4_DSN"):
        print("GUARDS VERDICT=FAIL reason=missing_dsn")
        return 2
    if not args.base_url:
        print("GUARDS VERDICT=FAIL reason=missing_base_url")
        return 2
    if not args.token:
        print("GUARDS VERDICT=FAIL reason=missing_g51_token")
        return 2

    python = sys.executable
    jobs = [
        ("G18b", [python, str(LEGACY / "G18b_parity.py"), "--pid", args.pid]),
        ("G24", [python, str(LEGACY / "G24_leaves.py"), "--pid", args.pid]),
        ("G24b", [python, str(LEGACY / "G24b_identity_leak.py"), "--pid", args.pid]),
        ("G32", [python, str(LEGACY / "G32_procedures_vs_event_pair.py"), "--pid", args.pid]),
        ("G51", [
            python, str(LEGACY / "G51_metrics_catalog_regression.py"),
            "--base-url", args.base_url, "--token", args.token,
            "--project", args.pid, "--capture", args.capture,
        ]),
        ("G56", [
            python, str(ROOT / "scripts" / "guards" / "G56_proven_links.py"),
            "--base-url", args.base_url, "--token", args.token,
            "--project", args.pid,
            "--proven-capture", G56_PROVEN_CAPTURE,
            "--probable-capture", args.capture,
        ]),
    ]
    rows = []
    for name, command in jobs:
        verdict, duration, returncode = _run(name, command)
        rows.append((name, verdict, duration, returncode))

    print("\nGUARD  VERDICT  DURATION_S  EXIT")
    for name, verdict, duration, returncode in rows:
        print(f"{name:<6} {verdict:<7} {duration:>10.2f}  {returncode}")
    global_verdict = "PASS" if all(row[1] == "PASS" for row in rows) else "FAIL"
    print(f"GUARDS VERDICT={global_verdict} passed={sum(r[1] == 'PASS' for r in rows)}/{len(rows)}")
    return 0 if global_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
