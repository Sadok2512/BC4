#!/usr/bin/env bash
# G18 (0.17.0) : Assistant branché au LLM — robustesse + pas de fuite.
#
# Vérifie que :
# 1. enabled=false → /assistant renvoie 200 + claim UNAVAILABLE
#    'désactivé/non configuré'. Jamais 500.
# 2. enabled=true + base_url injoignable (127.0.0.1:1) → 200 + claim
#    UNAVAILABLE 'indisponible/réseau/timeout'. Jamais 500.
# 3. La clé en clair n'apparaît NI dans la réponse NI dans la DB
#    (settings_llm.api_key_cipher stocke un token Fernet gAAAAA…).
# 4. `warnings` est populé quand l'appel LLM a échoué (traçabilité UI).
# 5. Nettoyage : la clé est vidée en fin de garde (api_key_set=false).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G18 impossible."
fi
if [[ -z "${BC4_LLM_SECRET_KEY:-}" ]]; then
  echo "[G18] WARN: BC4_LLM_SECRET_KEY absent → test 'unreachable' sera skippé."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g18_llm_assistant.py" -v
echo "[G18] OK"
