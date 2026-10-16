#!/usr/bin/env bash
# G20 (0.18.0) : Value matrix (value × operator × band) sur `/dict/params`.
#
# Numéroté G20 parce que G16 (value_distribution), G17 (llm_settings),
# G18 (llm_assistant), G19 (llm_probe) sont pris par les lots précédents.
#
# Vérifie que :
# 1. `GET /dict/params?system=LTE` expose un champ `value_matrix`
#    non vide pour `rsrpResult`.
# 2. `sum(cell.count for cell in value_matrix) == row.count`.
# 3. Au moins une cellule porte `operator="non attribué"` OU
#    `band="non attribué"` (confirme que `COALESCE('non attribué')` est
#    appliqué sur les 30.5% d'occurrences NULL de TEST2).
# 4. Le filtre `operator=Orange` restreint le `value_matrix` à des
#    cellules avec `operator == "Orange"` exclusivement.
# 5. La formule 3GPP est préservée : `value_converted == str(int(value_raw) - 141)`.
# 6. Non-régression `buckets` (op × band) : champ toujours présent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G20 impossible."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g20_value_matrix.py" -v
echo "[G20] OK"
