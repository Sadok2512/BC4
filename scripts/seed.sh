#!/usr/bin/env bash
# Lance les migrations puis le seed idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

require_dsn
cd "$(dirname "$HERE")"
python -m alembic upgrade head
python -m app.seed.run
