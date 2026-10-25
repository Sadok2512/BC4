# Alembic replay proof — 0044/0045/0046

Date: 2026-10-25. Database: disposable `postgis/postgis:16-3.4` container
`bc4-replay-bc1-0046`, published only on `127.0.0.1:55446`. No command in
this proof targets the live BC4 database.

## Baseline failure

Command (before the patch):

```sh
BC4_DSN=postgresql+psycopg://postgres:<ephemeral>@127.0.0.1:55446/bc4_replay \
  python -m alembic upgrade head
```

Output excerpt is in `before-failure.txt`: PostgreSQL rejects the recreated
`nmf_metric_value` view because its `VALUES` list mixes `double precision` and
newly converted `text` columns.

## Empty database to head

The same command after the patch exits 0. `empty-upgrade-head.log` contains the
full Alembic migration output and `empty-head-version.txt` contains:

```text
0052_deep_2_50_cols
```

## Requested replay

```sh
python -m alembic downgrade 0045_settings_pkeys
python -m alembic upgrade head
```

Both commands exit 0. Outputs are in `downgrade-0052-to-0045.log` and
`reupgrade-0045-to-head.log`. Recorded revisions:

```text
0045_settings_pkeys
0052_deep_2_50_cols
```

`primary-keys-after-replay.txt` lists the primary key and column for every table
touched by 0045/0046. All 16 are present after the replay.

## View/type integrity

`schema-after-replay.txt` proves the sampled documented string columns are
`text` in both Light and Deep tables while `nmf_metric_value.value` remains
`double precision`. `cast-helper.txt` records the focused cast restoration
assertion.
