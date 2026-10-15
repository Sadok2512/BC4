#!/usr/bin/env bash
# G3 : NR peuplé pour "Paris 2026 Q1", vide pour "Rennes LTE (sans NR)".
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_api_base
wait_for_health "$BC4_API_BASE"
python -m pytest "$HERE/../tests/test_g3_nr_coverage.py" -v
echo "[G3] OK"
