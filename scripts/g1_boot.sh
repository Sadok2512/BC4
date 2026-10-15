#!/usr/bin/env bash
# G1 : migrations appliquées + API démarre + /health OK + docker-compose up lance db+api+front.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_api_base
echo "[G1] Vérification /health sur $BC4_API_BASE"
wait_for_health "$BC4_API_BASE"
echo "[G1] /health OK"

echo "[G1] État docker-compose (optionnel — ignore si pas lancé via compose)"
if command -v docker >/dev/null 2>&1 && [[ -f "$(dirname "$HERE")/../docker-compose.yml" ]]; then
  (cd "$(dirname "$HERE")/.." && docker compose ps) || true
fi

python -m pytest "$HERE/../tests/test_g1_boot.py" -v
echo "[G1] OK"
