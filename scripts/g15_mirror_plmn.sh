#!/usr/bin/env bash
# G15 (0.14.0) : Fix bug mirror captures + PLMN non catalogué visible
# + doctrine opérateur = PLMN primaire du SIB1 (bc4-enrich 1.2.0).
#
# Numéroté G15 : G13 (périmètre) et G14 (dictionnaire) sont pris.
#
# Vérifie que :
# 1. Un projet seedé B0 (`n_captures_ingest=0`) garde ses captures après
#    `refresh_project_summary` (bug 0.13.0 → 0.14.0).
# 2. bc4-enrich 1.2.0 n'étiquette PAS un PLMN MVNO (ex. `20825`) :
#    il reste dans `plmns_unknown` et remonte en « PLMN 20825 (non
#    catalogué) » via `app/ingest/nmf.py`.
# 3. Un PLMN hors table (`20899`) remonte en « PLMN 20899 (non catalogué) »
#    dans `project.operators` — jamais silencieusement en N/D.
# 4. TEST2 (ingest réel) reste cohérent après un refresh.
# 5. La table `PLMN_TO_OPERATOR` contient exactement les 11 PLMN MNO FR.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G15 impossible."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g15_mirror_plmn.py" -v
echo "[G15] OK"
