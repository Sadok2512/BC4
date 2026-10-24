#!/bin/sh
# Lance tous les gardes du lot 2026-10. À exécuter dans bc4-api-1.
#   docker exec -w /app bc4-api-1 sh scripts/guards_2026_10/run_all.sh
set -eu
DIR="$(dirname "$0")"
for g in G29_file_vs_db G26_offsets G27_unk G28_ranges G24_leaves G25_catalogue G18b_parity GPS_stale; do
  echo "===================== $g ====================="
  python "$DIR/$g.py" 2>&1
  echo ""
done
