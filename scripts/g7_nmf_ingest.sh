#!/usr/bin/env bash
# G7 : garde manuelle B1-ingest (après câblage à `bc4_decoder 1.0.0`).
#
# Vérifie :
# - création d'un projet draft via POST /projects ;
# - upload NMF streamé via POST /projects/{id}/nmf (idempotent sur sha256) ;
# - GET /projects/{id}/import renvoie un NmfImportReport dont les comptes
#   collent au comptage RÉEL du décodeur en ligne de commande.
#
# Modes :
# - Si `BC4_NMF_WITNESS` est fourni et pointe vers un .nmf lisible :
#     * on lance le décodeur en CLI direct (via `BC4_NMF_DECODER_PATH`
#       ou `/opt/nmf_decoder` ou `/home/devmat/BC4/decoder`) :
#         python3 <root>/bc4_decoder.py <témoin.nmf>
#       → la ligne de sortie contient `events signalisation <N>` ;
#     * on compare `<N>` avec le `n_events` renvoyé par GET /projects/{id}/import ;
#     * on exige que le fichier soit en `status=done` côté API.
# - Sans `BC4_NMF_WITNESS` : la garde reste gracieuse — pytest valide
#   l'upload/idempotence et déclare l'écart ouvert (décodeur non éprouvé
#   contre un vrai NMF). Jamais de chiffre inventé.
#
# Préalables : BC4_DSN, BC4_API_BASE.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
require_api_base
wait_for_health "$BC4_API_BASE"

# ---------------------------------------------------------------------------
# Résolution du chemin décodeur côté hôte (pour l'appel CLI de comparaison).
# L'ordre est identique à `resolve_decoder()` côté Python.
# ---------------------------------------------------------------------------
pick_decoder_root() {
  local candidates=(
    "${BC4_NMF_DECODER_PATH:-}"
    "/opt/nmf_decoder"
    "/home/devmat/nmf_decoder"
    "/home/devmat/BC4/decoder"
  )
  for c in "${candidates[@]}"; do
    [[ -z "$c" ]] && continue
    if [[ -f "$c/bc4_decoder.py" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Comparaison CLI vs API — n'exécute que si témoin fourni ET lisible.
# ---------------------------------------------------------------------------
WITNESS="${BC4_NMF_WITNESS:-}"
if [[ -n "$WITNESS" ]]; then
  if [[ ! -f "$WITNESS" ]]; then
    shout "BC4_NMF_WITNESS=$WITNESS : fichier introuvable."
  fi
  DEC_ROOT="$(pick_decoder_root)" || shout "bc4_decoder.py introuvable dans les chemins candidats — pose-le ou exporte BC4_NMF_DECODER_PATH."
  echo "[G7] décodeur CLI : $DEC_ROOT/bc4_decoder.py"
  # Auto-test du décodeur sur le témoin : affiche la ligne
  # `bc4-decoder X.Y.Z — events signalisation N, dont géolocalisés G`.
  CLI_OUT="$(python3 "$DEC_ROOT/bc4_decoder.py" "$WITNESS")"
  echo "[G7] décodeur dit : $CLI_OUT"
  # Extraction du compte d'events depuis la ligne (motif stable, cf. source).
  CLI_N="$(echo "$CLI_OUT" | sed -n 's/.*events signalisation \([0-9]\+\).*/\1/p')"
  CLI_G="$(echo "$CLI_OUT" | sed -n 's/.*dont géolocalisés \([0-9]\+\).*/\1/p')"
  if [[ -z "$CLI_N" ]]; then
    shout "Impossible d'extraire le compte CLI depuis : $CLI_OUT"
  fi
  export BC4_G7_CLI_N_EVENTS="$CLI_N"
  export BC4_G7_CLI_N_GPS="${CLI_G:-0}"
fi

# ---------------------------------------------------------------------------
# Pytest G7 (crée projet, upload, idempotence, comparaison).
# ---------------------------------------------------------------------------
python -m pytest "$HERE/../tests/test_g7_nmf_ingest.py" -v

echo "[G7] OK"
