"""CLI de suppression projet-scopée d'une capture NMF.

Usage :
  python -m app.scripts.delete_capture PROJECT_ID CAPTURE_ID \
    --reason "justification opérateur"
"""
from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal
from app.services.capture_delete import (
    CaptureDeleteBusy,
    CaptureDeleteError,
    CaptureNotFound,
    delete_capture,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supprime une capture NMF d'un projet.")
    parser.add_argument("project_id")
    parser.add_argument("capture_id")
    parser.add_argument("--reason", required=True, help="Justification obligatoire (10 caractères minimum).")
    args = parser.parse_args(argv)

    try:
        with SessionLocal() as db:
            report = delete_capture(
                db, args.project_id, args.capture_id, reason=args.reason
            )
    except ValueError as exc:
        print(f"VERDICT=FAIL reason={exc}", file=sys.stderr)
        return 2
    except CaptureNotFound as exc:
        print(f"VERDICT=FAIL reason={exc}", file=sys.stderr)
        return 3
    except CaptureDeleteBusy as exc:
        print(f"VERDICT=FAIL reason={exc}", file=sys.stderr)
        return 4
    except CaptureDeleteError as exc:
        print(f"VERDICT=FAIL reason={exc}", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"VERDICT=FAIL reason=unexpected:{exc!r}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, default=str))
    print(f"VERDICT=PASS audit={report['audit_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
