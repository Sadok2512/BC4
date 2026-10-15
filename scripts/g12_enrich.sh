#!/usr/bin/env bash
# G12 (0.11.0) : bc4_enrich.detect_context décode SIB1 → operators + bands.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
if [[ -z "${BC4_NMF_DECODER_PATH:-}" ]]; then
  export BC4_NMF_DECODER_PATH=/home/devmat/BC4/decoder
fi
python -m pytest "$HERE/../tests/test_g12_enrich.py" -v
echo "[G12] OK"
