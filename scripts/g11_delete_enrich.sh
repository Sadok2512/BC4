#!/usr/bin/env bash
# G11 : DELETE /projects/{id} + enrichissement technologies + état seed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G11 impossible."
fi

python -m pytest "$HERE/../tests/test_g11_delete_project.py" -v
echo "[G11] OK"
