#!/usr/bin/env bash
# G13 (0.12.0) : enrich 1.1.0 (ctx["cells"]) + jointure cells Orange ↔
# cell_ref → project.perimeter. Garde unitaire + jointure base locale.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
if [[ -z "${BC4_NMF_DECODER_PATH:-}" ]]; then
  export BC4_NMF_DECODER_PATH=/home/devmat/BC4/decoder
fi
python -m pytest "$HERE/../tests/test_g13_perimeter.py" -v
echo "[G13] OK"
