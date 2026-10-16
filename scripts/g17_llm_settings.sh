#!/usr/bin/env bash
# G17 (0.16.0) : Settings LLM — chiffrement + admin-only + pas de fuite.
#
# Numéroté G17 : G13..G16 pris par les lots précédents.
#
# Vérifie que :
# 1. GET /settings/llm sans Bearer → 401.
# 2. GET /settings/llm pour un ingénieur → 403.
# 3. GET /settings/llm pour un admin → 200 + shape attendue, PAS de clé en clair.
# 4. PUT /settings/llm pour un ingénieur → 403.
# 5. PUT /settings/llm pour un admin → 200, `api_key_set=true`, clé en DB chiffrée (préfixe `gAAAAA`).
# 6. PUT /settings/llm avec `api_key=""` vide le cipher (`api_key_set=false`).
# 7. Les logs côté API ne contiennent JAMAIS la clé en clair (grep hors-process :
#    la méthode fiable est d'exiger que la DB ne stocke jamais la clé en clair).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G17 impossible."
fi
if [[ -z "${BC4_DEMO_EMAIL:-}" || -z "${BC4_DEMO_PASSWORD:-}" ]]; then
  shout "BC4_DEMO_EMAIL / BC4_DEMO_PASSWORD manquants — garde G17 impossible (403 ingénieur)."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g17_llm_settings.py" -v
echo "[G17] OK"
