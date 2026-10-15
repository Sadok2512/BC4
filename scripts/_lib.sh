#!/usr/bin/env bash
# Shared helpers for guard scripts. A guard that skips silently guards nothing —
# every helper here fails loudly when a prerequisite is missing.
set -euo pipefail

shout() {
  echo >&2 ""
  echo >&2 "!! $*"
  echo >&2 ""
  exit 2
}

require_dsn() {
  if [[ -z "${BC4_DSN:-}" ]]; then
    shout "BC4_DSN manquant — exportez le DSN avant de lancer la garde."
  fi
}

require_api_base() {
  if [[ -z "${BC4_API_BASE:-}" ]]; then
    shout "BC4_API_BASE manquant (ex: http://localhost:8000) — exportez-le."
  fi
}

wait_for_health() {
  local base="$1"
  local tries=40
  while (( tries > 0 )); do
    if curl -fsS "${base%/}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    tries=$((tries - 1))
  done
  shout "API ${base} injoignable (pas de /health 200 après 40s)."
}
