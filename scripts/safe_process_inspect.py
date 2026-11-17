#!/usr/bin/env python3
"""Inspect process command lines without disclosing credentials.

This is the only supported replacement for piping ``ps`` output directly to
grep/rg during production diagnostics.  Redaction happens in memory before a
matching line can reach stdout.
"""

from __future__ import annotations

import argparse
import re
import subprocess


SENSITIVE_NAME = (
    r"(?:BC4_DSN|BC4_PGPW|POSTGRES_PASSWORD|BC4_JWT_SECRET|"
    r"BC4_LLM_SECRET_KEY|[A-Z0-9_]*(?:API_KEY|PASSWORD|SECRET|TOKEN))"
)
ASSIGNMENT = re.compile(rf"(?i)(\b{SENSITIVE_NAME}=)([^\s]+)")
OPTION = re.compile(
    r"(?i)(--(?:password|secret|token|api[-_]key)(?:=|\s+))([^\s]+)"
)
URL_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)")


def redact_process_line(line: str) -> str:
    line = ASSIGNMENT.sub(r"\1<redacted>", line)
    line = OPTION.sub(r"\1<redacted>", line)
    return URL_CREDENTIAL.sub(r"\1<redacted>\3", line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match", required=True, help="case-insensitive regex")
    args = parser.parse_args()
    matcher = re.compile(args.match, re.IGNORECASE)
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,etime=,stat=,args="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for raw_line in result.stdout.splitlines():
        safe_line = redact_process_line(raw_line)
        if matcher.search(safe_line):
            print(safe_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
