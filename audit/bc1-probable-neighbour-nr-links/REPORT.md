# bc1/probable-neighbour-nr-links — report

## Outcome and contract

Back SemVer: **MINOR** (optional response fields plus Alembic 0078/0079;
BC3 assigns the number). Existing proven links are applied first and never
overwritten. The declared cap is **N=1**, the strongest LTE neighbour by
persisted `cell_rsrp`; deterministic identity fields break ties. Probable
matching uses system + derived band + PCI when available, then the nearest
same-band reference when no PCI candidate exists, always within 10 km.
PSCell 199 is preferred over NR types 1000–1002 for the optional NR anchor.

The links are materialized during `populate_chain`. Alembic 0078 adds the
strength used for ranking; 0079 adds capture-scoped materialized rows and
state, with `(project_id,capture_id,seq)` as the unique canonical key. The
idempotent backfill requires `--reason`, the BC3 deploy lock, and reads only
existing tables (no decode). A changed cell-reference import version makes a
cache stale, so the route computes current data rather than serving it.
Each row stores one compact JSON payload, avoiding three JSON conversions per
point while preserving the HTTP response byte-for-byte.

## Disposable proof commands

G36 before creating the stack:

```sh
df -h /home/devmat/BC4
```

Result: 142G available, PASS (threshold 20G).

The local dump `/home/devmat/BC4/exports/bc4_2026-10-30_0200.dump` was restored
into `bc1_probable_links`; no production endpoint or database was accessed.
The three captures were rematerialized with:

```sh
docker exec -i bc1-probable-links-api python - <<'PY'
from app.db import SessionLocal
from app.kpi.probable_link_materialized import materialize_project
with SessionLocal() as db:
    print(materialize_project(db, '43e81a34a073'))
PY
```

Result: 8,253 materialized point identities over the three captures.

Cold route measurement (API container restarted, health ready, then curl;
the sequence was repeated three times):

```sh
URL='http://127.0.0.1:9290/projects/43e81a34a073/metrics/map?capture_id=a4b0c321c52e&codes=cell_rsrp%40lte-type-0'
curl -sS -H "Authorization: Bearer $(< /tmp/bc1-probable-token)" \
  -D /tmp/bc1-probable-a4b0c321c52e.headers \
  -o /tmp/bc1-probable-a4b0c321c52e.final.json \
  -w 'http=%{http_code} starttransfer=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' "$URL"
```

Results: HTTP 200 and 7,077,800 bytes on every run. Cold start-transfer times
were 0.929685 s, 0.938304 s and 0.872701 s. The slowest run's
`Server-Timing` was dataset 8.853 ms, metric 278.035 ms, GPS 0.216 ms, links
495.485 ms. **PASS `< 1 s` on all three cold runs.**

Response preservation across the cache compaction:

```sh
sha256sum /tmp/bc1-probable-a4b0c321c52e.final.json \
  /tmp/bc1-probable-compact-{1,2,3}.json
cmp -s /tmp/bc1-probable-a4b0c321c52e.final.json \
  /tmp/bc1-probable-compact-1.json; echo response_cmp_exit=$?
```

All four SHA-256 values are
`8a0e5c4862104715ea85271c851eeb59808afacb8dc87ba94b170d07d4f5c281`;
`response_cmp_exit=0`.

The two other responses were fetched with the identical route/path and only
the capture id changed. Content proof:

```sh
python3 audit/bc1-probable-neighbour-nr-links/measure_response.py \
  a4b0c321c52e=/tmp/bc1-probable-a4b0c321c52e.final.json \
  daa2b1df250d=/tmp/bc1-probable-daa2b1df250d.final.json \
  ecffb18dbd7f=/tmp/bc1-probable-ecffb18dbd7f.final.json
```

Results:

| capture | response points | points with probable LTE neighbour | average LTE distance | points with probable NR anchor | average NR distance |
|---|---:|---:|---:|---:|---:|
| a4b0c321c52e | 4,935 | 4,074 | 710.264 m | 2,685 | 679.206 m |
| daa2b1df250d | 198 | 198 | 70.786 m | 15 | 221.800 m |
| ecffb18dbd7f | 199 | 199 | 65.117 m | 107 | 219.393 m |

Every response has at most one neighbour. Independent haversine recomputation
of every returned link differs by at most 0.049984 m from the rounded API
distance. Five distinct `(capture, kind, cell_ref, ARFCN, PCI)` examples are
printed by the same command; all five are within 0.034 m of the independent
calculation. Thus coordinates, distance and 10 km bound are checked by
content, not by labels.

## Guard and test verdicts

```sh
docker exec bc1-probable-links-api python -m pytest -q \
  tests/test_map_cell_links.py tests/test_metrics_v3.py \
  tests/test_operational_write_guards.py tests/test_deploy_guard.py
```

Result: 14 passed, exit 0, VERDICT=PASS. Alembic downgrade 0079→0078 and
upgrade 0078→0079 both exited 0. The backfill refused without a lock with
exit 1 and explicit `VERDICT=FAIL reason=deploy_lock_required` (expected
guard result), then completed with exit 0 and `VERDICT=PASS` using a
disposable fixture whose sole holder was BC3.

Setup diagnostics closed explicitly: initial restore before PostgreSQL's init
restart (exit 1) succeeded on retry; two incorrect schema inventory names
(exit 1) were replaced after `\d`; an Alembic wait-loop timeout (exit 124) was
closed by revision/index inspection; early unoptimized endpoint calls timed
out (exit 28) and were replaced by the three bounded measurements above; one
aggregate control query had an invalid `ORDER BY` (exit 1) and was rerun with
`ON_ERROR_STOP`, canonical `(project_id,capture_id)` ordering and exit 0.
No test was skipped.
