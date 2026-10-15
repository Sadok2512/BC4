#!/usr/bin/env bash
# G2 : chaque endpoint valide contre son schéma (parité Pydantic ↔ Zod).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_api_base
wait_for_health "$BC4_API_BASE"
python -m pytest "$HERE/../tests/test_g2_parity.py" -v
echo "[G2] OK"
