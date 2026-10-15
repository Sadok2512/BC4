#!/usr/bin/env bash
# G10 (P1-2) : POST /settings/users + password policy + mapping 3-rôles.
# Crie si DSN/API/admin/demo absents.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G10 impossible."
fi
if [[ -z "${BC4_DEMO_EMAIL:-}" || -z "${BC4_DEMO_PASSWORD:-}" ]]; then
  shout "BC4_DEMO_EMAIL / BC4_DEMO_PASSWORD manquants (compte ingenieur attendu)."
fi

python -m pytest "$HERE/../tests/test_g10_users_policy_roles.py" -v
echo "[G10] OK"
