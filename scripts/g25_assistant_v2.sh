#!/usr/bin/env bash
# G25 (0.25.0) — Assistant V2 : catalogue + moteur + preuves + agent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
[[ -z "$PY" ]] && shout "python introuvable."
"$PY" -m pytest "$HERE/../tests/test_g25_assistant_v2.py" -v
echo "[G25] OK"
