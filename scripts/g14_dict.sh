#!/usr/bin/env bash
# G14 (0.13.0) : Dictionnaire complet RRC LTE+NR (param_occurrence).
#
# Numéroté G14 (et non G13) parce qu'un lot parallèle 0.12.0 (Agent BC1,
# périmètre géo cells Orange ↔ cell_ref) occupe déjà G13.
#
# Vérifie que :
# 1. `param_occurrence` est peuplée pour TEST2 (count > 0).
# 2. `GET /projects/{TEST2}/dict/tree` → 2 branches LTE/NR non vides.
# 3. `GET /projects/{TEST2}/dict/params?system=LTE&message=SystemInformationBlockType1`
#    expose `q-RxLevMin` (ou similaire) avec `value_converted` non null.
# 4. `GET /projects/{TEST2}/dict/param/map?path=…&system=LTE` → len(points) > 0.
# 5. Aucun path DENY (`ue-Identity|s-TMSI|dedicatedNAS|…`) ne sort de
#    `/dict/params` ni de `param_occurrence`.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G14 impossible."
fi

# On préfère `python` dans l'image Docker ; `python3` en host (G1–G12
# standard). Même pattern que les autres gardes (voir g12_enrich.sh).
PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g14_dict.py" -v
echo "[G14] OK"
