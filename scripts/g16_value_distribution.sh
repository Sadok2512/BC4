#!/usr/bin/env bash
# G16 (0.15.0) : Distribution par valeur sur `/dict/params`.
#
# Numéroté G16 : G13 (périmètre), G14 (dictionnaire), G15 (mirror/PLMN)
# sont pris par les lots précédents.
#
# Vérifie que :
# 1. `GET /dict/params?system=LTE` expose un champ `value_distribution`
#    non vide pour un paramètre numérique peuplé (rsrpResult).
# 2. La somme des `count` dans `value_distribution` == count global
#    du paramètre.
# 3. La formule 3GPP est appliquée (rsrpResult : idx - 141 = dBm).
# 4. Un paramètre enum (dl-Bandwidth) renvoie `value_converted=null`.
# 5. Le filtre `operator=Orange` restreint strictement la distribution.
# 6. Les buckets (op × band) existants restent présents (non-breaking).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G16 impossible."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g16_value_distribution.py" -v
echo "[G16] OK"
