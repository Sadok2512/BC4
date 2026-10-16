#!/usr/bin/env bash
# 0.30.0 — Ingère les 18 NMF témoins Petite-Forêt dans un projet
# REF_PETITE_FORET fraîchement créé. Jamais d'invention : chaque réponse
# API (files_done / files_error) est reportée telle quelle.
#
# Variables requises :
#   BC4_API_BASE       (ex: http://localhost:8000)
#   BC4_DEMO_EMAIL     (compte seedé via docker-compose)
#   BC4_DEMO_PASSWORD
# Variables optionnelles :
#   BC4_WITNESS_DIR    (défaut: /home/devmat/BC4/witness-nmf)
set -euo pipefail

API="${BC4_API_BASE:-http://localhost:8000}"
EMAIL="${BC4_DEMO_EMAIL:?BC4_DEMO_EMAIL requis}"
PASS="${BC4_DEMO_PASSWORD:?BC4_DEMO_PASSWORD requis}"
WITNESS="${BC4_WITNESS_DIR:-/home/devmat/BC4/witness-nmf}"

echo "[ingest-ref] API=$API"
echo "[ingest-ref] WITNESS=$WITNESS"

TOKEN=$(curl -sS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "[ingest-ref] login failed" >&2
  exit 2
fi
echo "[ingest-ref] token OK"

# 0.33.0 — Idempotence stricte : si `BC4_REF_PID` est passé en env, on
# l'utilise verbatim (évite toute création en double). Sinon, on CHERCHE
# D'ABORD un projet nommé `REF_PETITE_FORET` via GET /projects. On ne
# crée un nouveau projet QUE si aucun n'existe (sinon on avait 2
# projets avec le même nom, bug 0.32.0).
PID="${BC4_REF_PID:-}"
if [[ -z "$PID" ]]; then
  PID=$(curl -sS "$API/projects" -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json
try:
  d = json.load(sys.stdin)
except Exception:
  sys.exit(0)
for p in d or []:
  if p.get('name') == 'REF_PETITE_FORET':
    print(p.get('id','')); break")
fi
if [[ -z "$PID" || "$PID" == "null" ]]; then
  # Aucun projet existant → on crée (une seule fois).
  PID=$(curl -sS -X POST "$API/projects" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"name":"REF_PETITE_FORET"}' \
    | python3 -c "import sys,json;
try: d=json.load(sys.stdin); print(d.get('id','') if isinstance(d, dict) else '')
except Exception: print('')")
fi
if [[ -z "$PID" || "$PID" == "null" ]]; then
  echo "[ingest-ref] projet REF_PETITE_FORET introuvable et création KO" >&2
  exit 2
fi
echo "[ingest-ref] REF_PETITE_FORET id=$PID"

total=0
done_cnt=0
err_cnt=0
dup_cnt=0

while IFS= read -r -d '' f; do
  total=$((total+1))
  resp=$(curl -sS -X POST "$API/projects/$PID/nmf" \
    -H "Authorization: Bearer $TOKEN" \
    -F "files=@${f}")
  d=$(echo "$resp" | python3 -c "import sys,json;
try: print(json.load(sys.stdin).get('files_done',0))
except Exception: print(0)")
  e=$(echo "$resp" | python3 -c "import sys,json;
try: print(json.load(sys.stdin).get('files_error',0))
except Exception: print(0)")
  dup=$(echo "$resp" | python3 -c "import sys,json;
try: print(json.load(sys.stdin).get('files_duplicate',0))
except Exception: print(0)")
  done_cnt=$((done_cnt+d))
  err_cnt=$((err_cnt+e))
  dup_cnt=$((dup_cnt+dup))
  echo "  $(basename "$f") → done=$d err=$e dup=$dup"
done < <(find "$WITNESS" -type f -name '*.nmf' -print0 | sort -z)

echo "[ingest-ref] TOTAL=$total  done=$done_cnt  err=$err_cnt  duplicate=$dup_cnt"
echo "[ingest-ref] PID=$PID"
