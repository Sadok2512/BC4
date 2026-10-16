#!/usr/bin/env bash
# G22 (0.23.1) : Intent classifier /assistant (CONVERSATION vs ANALYSE).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G22 impossible."
fi
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
[[ -z "$PY" ]] && shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host)."
"$PY" -m pytest "$HERE/../tests/test_g22_intent.py" -v
echo "[G22] OK"
