#!/usr/bin/env bash
# G9 (P1-1) : CORS préflight depuis l'origine front + seed démo env-driven.
# Garde manuelle. Crie si DSN/API/admin absents.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G9 impossible."
fi

python -m pytest "$HERE/../tests/test_g9_cors_demo.py" -v
echo "[G9] OK"
