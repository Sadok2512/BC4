#!/usr/bin/env bash
# G23 (0.24.0 Keystone) — infrastructure extraction mesure+débit.
# Phase 1 (mapping) non testable sans NMF témoin : voir CHANGELOG.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"
if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G23 impossible."
fi
if [[ -z "${BC4_DEMO_EMAIL:-}" || -z "${BC4_DEMO_PASSWORD:-}" ]]; then
  shout "BC4_DEMO_EMAIL / BC4_DEMO_PASSWORD manquants — garde G23 impossible."
fi
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
[[ -z "$PY" ]] && shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host)."
"$PY" -m pytest "$HERE/../tests/test_g23_measurements_keystone.py" -v
echo "[G23] OK"
