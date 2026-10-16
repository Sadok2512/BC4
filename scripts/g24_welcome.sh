#!/usr/bin/env bash
# G24 (0.24.1) — présentation d'accueil structurée (5 points).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G24 impossible."
fi
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
[[ -z "$PY" ]] && shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host)."
"$PY" -m pytest "$HERE/../tests/test_g24_welcome.py" -v
echo "[G24] OK"
