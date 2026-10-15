#!/usr/bin/env bash
# G5 : aucune valeur en dur dans un handler — tout vient du seed en base
# (scan + test somme n = lignes en base).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
python -m pytest "$HERE/../tests/test_g5_db_sourced.py" -v
echo "[G5] OK"
