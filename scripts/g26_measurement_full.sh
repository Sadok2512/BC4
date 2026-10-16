#!/usr/bin/env bash
# G26 (0.30.0) — Garde manuelle : câblage décodeur 2.0.0 complet.
# (G23/G24/G25 déjà pris par les lots précédents BC1.)
#
# Vérifie :
#   - /health version ≥ 0.30.0
#   - stg_event_raw peuplée par catégorie (chaque catégorie > 0 pour les
#     NMF du corpus — gps/signalling toujours, cellmeas/cmdreq/data_*
#     attendus sur Petite-Forêt)
#   - stg_event (signalling) non vide
#   - nmf_file.dl / ts_label / env renseignés
#   - 18 fichiers .nmf présents sous BC4_NMF_SOURCE_DIR/<REF>/
#   - measurement_points.operator cohérent avec #DL
#   - operator_mismatch count
#   - RSRP cross-check cellmeas vs RRC
#   - zéro identité IMSI/IMEI (regex 15 chiffres)
#
# Dépend du script `ingest_ref_petite_foret.sh` (le fait tourner si
# aucun projet REF_PETITE_FORET n'est trouvé).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"
require_api_base
wait_for_health "$BC4_API_BASE"

echo "[G26] /health"
curl -fsS "$BC4_API_BASE/health" | tee /dev/stderr | grep -q '"version":"0.30' \
  || shout "/health ne renvoie pas la version 0.30.x"

# ------------------------------------------------------------
# Récupère ou crée le projet REF_PETITE_FORET et ingère si besoin.
# ------------------------------------------------------------
EMAIL="${BC4_DEMO_EMAIL:?BC4_DEMO_EMAIL requis}"
PASS="${BC4_DEMO_PASSWORD:?BC4_DEMO_PASSWORD requis}"
TOKEN=$(curl -sS -X POST "$BC4_API_BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | jq -r .token)

PID=$(curl -sS "$BC4_API_BASE/projects" -H "Authorization: Bearer $TOKEN" \
  | jq -r '.[] | select(.name=="REF_PETITE_FORET") | .id' | head -n1)

if [[ -z "$PID" || "$PID" == "null" ]]; then
  echo "[G26] REF_PETITE_FORET absent — ingestion"
  bash "$HERE/ingest_ref_petite_foret.sh"
  PID=$(curl -sS "$BC4_API_BASE/projects" -H "Authorization: Bearer $TOKEN" \
    | jq -r '.[] | select(.name=="REF_PETITE_FORET") | .id' | head -n1)
fi
echo "[G26] REF_PETITE_FORET id=$PID"

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
[[ -z "$PY" ]] && shout "python introuvable — exportez PYTHON=/usr/bin/python3"

BC4_REF_PID="$PID" "$PY" -m pytest "$HERE/../tests/test_g26_measurement_full.py" -v

echo "[G26] OK"
