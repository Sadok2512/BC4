#!/usr/bin/env bash
# G22 (0.22.3) : Désambigüisation des libellés d'arbre sur `/dict/tree`.
#
# Vérifie que :
# 1. Chaque param[] de `/dict/tree` v2 porte un champ `label` non vide.
# 2. Dans un même (system, message), aucun doublon de `label`.
# 3. Les leaves uniques (seul path portant ce dernier segment dans leur
#    message) gardent `label == leaf` — sans suffixe parenthésé.
# 4. Les leaves en collision (plusieurs paths partageant le même dernier
#    segment) portent un suffixe parenthésé `(…)`.
# 5. Non-régression : `param` reste le path complet, lookable via
#    `/dict/params?system=…` (une path en collision y est retrouvée).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

if [[ -z "${BC4_ADMIN_EMAIL:-}" || -z "${BC4_ADMIN_PASSWORD:-}" ]]; then
  shout "BC4_ADMIN_EMAIL / BC4_ADMIN_PASSWORD manquants — garde G22 impossible."
fi

PY="${PYTHON:-$(command -v python || command -v python3 || true)}"
if [[ -z "$PY" ]]; then
  shout "python introuvable — exportez PYTHON=/usr/bin/python3 (host) ou lancez via docker exec."
fi

"$PY" -m pytest "$HERE/../tests/test_g21_tree_label_dedup.py" -v
echo "[G22] OK"
