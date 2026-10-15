#!/usr/bin/env bash
# G4 : conversion 3GPP conforme à conversion_rule (non-régression numérique).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_api_base
wait_for_health "$BC4_API_BASE"
python -m pytest "$HERE/../tests/test_g4_conversion.py" -v
echo "[G4] OK"
