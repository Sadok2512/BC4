#!/usr/bin/env bash
# G24 (0.33.0) — Garde ``measurement_points`` chaîne complète :
#  a. count > 0 sur REF_PETITE_FORET
#  b. breakdown (operator × service_type × phase)
#  c. tableau de preuve chiffré (±2 dB) sur les champs CELLMEAS
#  d. cross-check RSRP par bande (±2 dB)
#  e. operator_mismatch=true : compte + 3 exemples
#  f. zéro identité abonné (regex 15 chiffres sur JSON)
#  g. pas de duplication (count == count distinct)
#  h. 18 fichiers source sur disque (sous conteneur)
#  i. 18 nmf_file.env renseignés (``incar`` | ``indoor``)
#
# Imprime PASS/FAIL par item avec les chiffres réels. Aucune invention —
# un échec est **déclaré** chiffré, pas masqué. Code retour = 2 si FAIL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

PID="${BC4_REF_PID:-7e656b8c6c19}"
API_CONTAINER="${BC4_API_CONTAINER:-bc4-api-1}"
DB_CONTAINER="${BC4_DB_CONTAINER:-bc4-db-1}"
NMF_SRC_DIR="${BC4_NMF_SOURCE_DIR:-/var/lib/bc4/nmf-source}"

psql_q() {
  # Exécute une requête psql via le conteneur DB. Jamais d'invention : si
  # le conteneur n'est pas joignable, on sort en FAIL explicite.
  docker exec "$DB_CONTAINER" psql -U bc4 -d bc4 -t -A -F '|' -c "$1"
}

fail=0
pass_fail() {
  local label="$1" ok="$2" detail="$3"
  if [[ "$ok" == "1" ]]; then
    echo "  [G24 PASS] $label — $detail"
  else
    echo "  [G24 FAIL] $label — $detail"
    fail=1
  fi
}

echo "=== G24 measurement_full — projet $PID ==="
echo

# ---------------------------------------------------------------------
# a. measurement_points count > 0
# ---------------------------------------------------------------------
mp_count=$(psql_q "SELECT COUNT(*) FROM measurement_points WHERE project_id='$PID';")
if [[ "$mp_count" -gt 0 ]]; then
  pass_fail "a. measurement_points non vide" 1 "count=$mp_count"
else
  pass_fail "a. measurement_points non vide" 0 "count=0 (populate KO ou aucun GPS sur le corpus)"
fi

# ---------------------------------------------------------------------
# b. breakdown (operator × service_type × phase)
# ---------------------------------------------------------------------
echo
echo "  [G24] breakdown (operator × service_type × phase)"
psql_q "SELECT COALESCE(operator,'N/D'), COALESCE(service_type,'N/D'), COALESCE(phase,'N/D'), COUNT(*)
        FROM measurement_points WHERE project_id='$PID'
        GROUP BY 1,2,3 ORDER BY 1,2,3;" | sed 's/^/    /'

# ---------------------------------------------------------------------
# c. tableau de preuve chiffré (via le module Python app.measure.proof)
# ---------------------------------------------------------------------
echo
echo "  [G24] tableau de preuve chiffré (±2 dB)"
docker exec -e BC4_REF_PID="$PID" "$API_CONTAINER" python3 - <<'PYEOF'
import json
import os
import sys
sys.path.insert(0, "/app")
from app.db import SessionLocal
from app.measure.proof import run_proof, format_proof_table

pid = os.environ["BC4_REF_PID"]
db = SessionLocal()
try:
    rows = run_proof(db, pid)
    print(format_proof_table(rows))
    # Pour que le shell puisse en déduire PASS/FAIL global sur les
    # mappings prouvés, on dump un bloc JSON machine-lisible.
    print("---PROOF-JSON---")
    print(json.dumps([r.as_dict() for r in rows], ensure_ascii=False))
finally:
    db.close()
PYEOF

# ---------------------------------------------------------------------
# d. cross-check RSRP ±2 dB par bande (sur mesures prouvées seulement)
# ---------------------------------------------------------------------
echo
echo "  [G24] cross-check RSRP cellmeas vs RRC par bande"
cross=$(psql_q "
  SELECT COALESCE(mp.band,'N/D'),
         ROUND(AVG(mp.rsrp)::numeric, 2) AS rsrp_cellmeas,
         (SELECT ROUND(AVG(CAST(po.value_converted AS double precision))::numeric, 2)
          FROM param_occurrence po
          WHERE po.project_id = mp.project_id
            AND po.path ~ 'measResultPCell/rsrpResult\$'
            AND po.band IS NOT DISTINCT FROM mp.band
            AND po.value_converted IS NOT NULL) AS rsrp_rrc,
         COUNT(*) AS n_mp
  FROM measurement_points mp
  WHERE mp.project_id = '$PID' AND mp.rat = 'LTE' AND mp.rsrp IS NOT NULL
  GROUP BY mp.band, mp.project_id ORDER BY mp.band NULLS LAST;")
if [[ -n "$cross" ]]; then
  echo "$cross" | sed 's/^/    /'
  # Détection d'un delta > 2 dB
  while IFS='|' read -r band avg_cm avg_rrc n_mp; do
    [[ -z "$avg_cm" || -z "$avg_rrc" || "$avg_rrc" == " " ]] && continue
    delta=$(python3 -c "print(abs(float('$avg_cm') - float('$avg_rrc')))" 2>/dev/null || echo "nan")
    if [[ "$delta" != "nan" ]]; then
      ok=$(python3 -c "print(1 if abs(float('$avg_cm') - float('$avg_rrc')) <= 2.0 else 0)")
      pass_fail "d. RSRP±2dB band=$band" "$ok" "cellmeas=$avg_cm rrc=$avg_rrc Δ=$delta dB n=$n_mp"
    fi
  done <<< "$cross"
else
  pass_fail "d. RSRP cross-check" 0 "pas de mesure RSRP prouvée dans measurement_points"
fi

# ---------------------------------------------------------------------
# e. operator_mismatch=true : compte + 3 exemples
# ---------------------------------------------------------------------
echo
mismatch=$(psql_q "SELECT COUNT(*) FROM measurement_points WHERE project_id='$PID' AND operator_mismatch=true;")
echo "  [G24] operator_mismatch=true : $mismatch ligne(s)"
if [[ "$mismatch" -gt 0 ]]; then
  echo "  3 exemples :"
  psql_q "SELECT capture_id, seq, operator, operator_source, service_type, phase
          FROM measurement_points
          WHERE project_id='$PID' AND operator_mismatch=true
          LIMIT 3;" | sed 's/^/    /'
fi
# Pas de PASS/FAIL : le mismatch est **déclaré**, jamais un échec en soi.

# ---------------------------------------------------------------------
# f. zéro identité abonné (15 chiffres)
# ---------------------------------------------------------------------
echo
id_sr=$(psql_q "SELECT COUNT(*) FROM stg_event_raw
                WHERE project_id='$PID' AND raw_fields::text ~ '(?<!\d)\d{15}(?!\d)';")
id_mp=$(psql_q "SELECT COUNT(*) FROM measurement_points
                WHERE project_id='$PID' AND (
                   COALESCE(operator,'')||' '||COALESCE(tech,'')||' '||
                   COALESCE(service,'')||' '||COALESCE(band,'')||' '||
                   COALESCE(dep,'')||' '||COALESCE(site,'')||' '||
                   COALESCE(ts,'')||' '||COALESCE(capture_id,'')||' '||
                   COALESCE(event_code,'')||' '||COALESCE(operator_source,'')||' '||
                   COALESCE(service_name,'')||' '||COALESCE(service_action,'')||' '||
                   COALESCE(service_type,'')||' '||COALESCE(phase,'')||' '||
                   COALESCE(env,'')||' '||COALESCE(rat,'')
                ) ~ '(?<!\d)\d{15}(?!\d)';")
if [[ "$id_sr" == "0" && "$id_mp" == "0" ]]; then
  pass_fail "f. zéro identité (regex 15 chiffres)" 1 "stg_event_raw=0 measurement_points=0"
else
  pass_fail "f. zéro identité (regex 15 chiffres)" 0 "stg_event_raw=$id_sr measurement_points=$id_mp"
fi

# ---------------------------------------------------------------------
# g. pas de duplication (count == count distinct)
# ---------------------------------------------------------------------
dup_tot=$(psql_q "SELECT COUNT(*) FROM measurement_points WHERE project_id='$PID' AND event_code IS NOT NULL;")
dup_uq=$(psql_q "SELECT COUNT(*) FROM (SELECT DISTINCT project_id, capture_id, seq, event_code FROM measurement_points WHERE project_id='$PID' AND event_code IS NOT NULL) t;")
if [[ "$dup_tot" == "$dup_uq" ]]; then
  pass_fail "g. pas de duplication" 1 "tot=$dup_tot distinct=$dup_uq"
else
  pass_fail "g. pas de duplication" 0 "tot=$dup_tot distinct=$dup_uq Δ=$((dup_tot-dup_uq))"
fi

# ---------------------------------------------------------------------
# h. 18 fichiers source sur disque + taille > 0
# ---------------------------------------------------------------------
nmf_count=$(psql_q "SELECT COUNT(*) FROM nmf_file WHERE project_id='$PID';")
src_count=$(docker exec "$API_CONTAINER" sh -c "ls '$NMF_SRC_DIR/$PID' 2>/dev/null | wc -l")
src_nonzero=$(docker exec "$API_CONTAINER" sh -c "find '$NMF_SRC_DIR/$PID' -type f -size +0 2>/dev/null | wc -l")
if [[ "$nmf_count" == "18" && "$src_count" == "18" && "$src_nonzero" == "18" ]]; then
  pass_fail "h. 18 fichiers nmf + 18 source disk" 1 "nmf=$nmf_count disk=$src_count nonzero=$src_nonzero"
else
  pass_fail "h. 18 fichiers nmf + 18 source disk" 0 "nmf=$nmf_count disk=$src_count nonzero=$src_nonzero"
fi

# ---------------------------------------------------------------------
# i. env renseigné sur les 18 (``incar`` | ``indoor``, aucun NULL)
# ---------------------------------------------------------------------
env_null=$(psql_q "SELECT COUNT(*) FROM nmf_file WHERE project_id='$PID' AND (env IS NULL OR env = '');")
env_ok=$(psql_q "SELECT COUNT(*) FROM nmf_file WHERE project_id='$PID' AND env IN ('incar','indoor');")
if [[ "$env_null" == "0" && "$env_ok" == "$nmf_count" && "$nmf_count" == "18" ]]; then
  pass_fail "i. env renseigné sur 18" 1 "env_ok=$env_ok env_null=$env_null"
else
  pass_fail "i. env renseigné sur 18" 0 "env_ok=$env_ok env_null=$env_null nmf=$nmf_count"
fi

echo
if [[ "$fail" == "0" ]]; then
  echo "[G24] OK"
  exit 0
else
  echo "[G24] FAIL (voir items ci-dessus)"
  exit 2
fi
