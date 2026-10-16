#!/usr/bin/env bash
# G21 (0.22.0) : contexte factuel enrichi /assistant (+ RRC).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G21 impossible."
fi
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host)."
fi
"$PY" -m pytest "$HERE/../tests/test_g21_assistant_context.py" -v
echo "[G21] OK"
