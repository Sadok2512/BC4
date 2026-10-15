#!/usr/bin/env bash
# G8 : auth comptes locaux. Crie si DSN/API/admin creds absents.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G8 impossible."
fi

python -m pytest "$HERE/../tests/test_g8_auth.py" -v
echo "[G8] OK"
