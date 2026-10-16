#!/usr/bin/env bash
# G19 (0.17.1) : Probe /settings/llm/test — admin-only, pas de fuite.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G19 impossible."
fi
if [[ -z "${BC4_DEMO_EMAIL:-}" || -z "${BC4_DEMO_PASSWORD:-}" ]]; then
  shout "BC4_DEMO_EMAIL / BC4_DEMO_PASSWORD manquants — garde G19 impossible."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g19_llm_probe.py" -v
echo "[G19] OK"
