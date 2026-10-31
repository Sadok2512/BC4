# bc1/guard-proven-links — G56

## Result

Back SemVer: **PATCH 0.118.2**, numbered and deployed by BC1 after BC3 was
removed from deployment duty. The HTTP contract is unchanged.
The proven-serving invariant is centralized in
`preserve_proven_serving_links()` and runs before live/cache branching. G56 is
fail-closed on missing URL/token, HTTP failure, malformed JSON, any proven
count mismatch, or a probable count below the declared floor.

## Disposable-stack proof

G36 before stack creation:

```sh
df -h /home/devmat/BC4
```

Result: 125G available, PASS against the 20G floor.

The local file `/home/devmat/BC4/exports/bc4_2026-10-31_0200.dump` was restored
to `bc1_g56`; no production endpoint or database was accessed. Its restored
revision was measured as 0077, then upgraded through 0078/0079 and Test_6 was
materialized from the restored tables. The final guard was invoked inside the
disposable API with a five-minute token generated in memory for the project
owner; the token was never printed or written:

```sh
docker exec -i bc1-g56-api python - <<'PY'
from sqlalchemy import text
from app.config import settings
from app.db import SessionLocal
from app.services.auth import create_token
from scripts.guards.G56_proven_links import main
with SessionLocal() as db:
    row = db.execute(text("""SELECT u.id,u.role FROM projects p
      JOIN app_user u ON u.id=p.owner_id
      WHERE p.id='43e81a34a073'""")).one()
token, _ = create_token(user_id=row.id, role=row.role, ttl_min=5,
                        secret=settings.jwt_secret)
raise SystemExit(main([
  '--base-url','http://127.0.0.1:8000','--token',token,
  '--project','43e81a34a073',
  '--proven-capture','ecffb18dbd7f',
  '--probable-capture','a4b0c321c52e']))
PY
```

Output:

```text
G56 content project=43e81a34a073 proven_capture=ecffb18dbd7f proven_points=199 proven_marked=199 probable_capture=a4b0c321c52e probable_points=4935 probable_serving=4435
G56 VERDICT=PASS
g56_exit=0
```

## Unit guards

```sh
python3 -m pytest -q tests/test_guard_g56.py tests/test_guard_harness.py \
  tests/test_proven_link_invariant.py tests/test_map_cell_links.py
```

Final result in the application image: 26 passed, exit 0, no SKIP.

## Non-zero setup commands closed

- Running Git from `/home/devmat/BC4` exited non-zero because it is an
  orchestration directory; the dedicated worktree was then created from back
  `main` 0.118.1.
- Restore polling intentionally returned exit 124 while `pg_restore` was
  active; `pg_stat_activity` showed progressing COPY/index work. Closure:
  restored Test_6 was found by content and Alembic reported 0077.
- Querying `nmf_probable_cell_link` immediately after the 0077 restore exited
  non-zero because the table is introduced by 0079. Closure: Alembic upgraded
  to 0079 and materialization returned exit 0.
- The first migration attempt used unsupported `BC4_ENV=test` and exited 1.
  It was rerun with accepted disposable value `development`, exit 0.
- The first API start omitted mandatory `BC4_ADMIN_EMAIL` and exited 1.
  The restored DB contained `admin@bc4.local`; relaunch supplied that email
  only (no password supplied) and reached `/health`.
- One host test collection exited 2 because fail-fast configuration lacked
  `BC4_DSN` and `BC4_JWT_SECRET`; no test ran. It was rerun with disposable
  non-routable values and all 26 tests passed with exit 0.

No test was skipped and no production action was performed.

## Deployment verification

After the disposable proof above, BC1 deployed the accepted lot under the
exclusive BC1 lock. `scripts/guards/run_all.py --skip-g51` returned PASS for
G18b, G24, G24b, G32 and G56 (`passed=5/5`, every exit code zero). Public
Playwright verification through `http://185.248.33.125:5174` returned HTTP
200 for Overview, KPI, Map and Signaling, with no API failure or console
error. The report and screenshots are archived under
`/home/devmat/BC4/audit/deploy-back-0.118.2/`.
