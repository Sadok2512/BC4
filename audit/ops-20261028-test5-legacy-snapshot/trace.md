# Opération 2026-10-28 — backfill snapshot legacy Test_5

**Contexte** : le job `c67112ccda3d4e39aae5bc1ffb171904` (projet Test_5
`d8d14aefa51f`) a été créé avant la migration `0061_import_job_parsing_snapshot`.
Ses 6 colonnes de snapshot d'import étaient toutes `NULL`. La garde
`parsing_snapshot()` du worker (0061) refuse donc tout retry :

```
ERROR:__main__:Import failed job=c67112ccda3d4e39aae5bc1ffb171904
  File "/app/app/services/import_worker.py", line 34, in parsing_snapshot
    raise ValueError('import_job_parsing_snapshot_missing')
ValueError: import_job_parsing_snapshot_missing
```

Opération unique autorisée par Codex67 (via BC3) : backfill via la MÊME
logique applicative que `app.services.import_jobs.enqueue()` lignes 76-82
(4 defaults projet + 2 constantes code). Aucune valeur tapée à la main.

## Lancement

```
docker compose stop import-worker
docker cp audit/ops-20261028-test5-legacy-snapshot/backfill_test5_legacy_snapshot.py \
  bc4-api-1:/tmp/backfill_test5_legacy_snapshot.py
docker exec -w /app -e PYTHONPATH=/app bc4-api-1 \
  python /tmp/backfill_test5_legacy_snapshot.py
```

## Sortie 1re exécution (effective)

```
BEFORE job snapshot:
  decode_level = None
  binning_mode = None
  temporal_resolution = None
  spatial_bin_m = None
  aggregation_contract_version = None
  decoder_version = None

AFTER job snapshot:
  decode_level = 'deep'
  binning_mode = 'temporal'
  temporal_resolution = 'native'
  spatial_bin_m = None
  aggregation_contract_version = 'query-binning-v1'
  decoder_version = '1.7.2'

nmf_capture.decoder_version pour project (inchangé par ce backfill) :
  1.7.1 → 22 captures

OK — backfill snapshot legacy Test_5 appliqué, worker peut reprendre
```

## Idempotence stricte vérifiée (2e exécution)

Voir `backfill_exec.log` : la 2e exécution refuse avec exit=3 car les
6 colonnes ne sont plus toutes NULL.

```
REFUSE: job snapshot déjà rempli sur ['decode_level', 'binning_mode',
'temporal_resolution', 'aggregation_contract_version', 'decoder_version']
— opération non idempotente
```

## Preuves SQL

`job_snapshot_after.txt` :

```
id                               | decode_level | binning_mode | temporal_resolution | spatial_bin_m | aggregation_contract_version | decoder_version
---------------------------------+--------------+--------------+---------------------+---------------+------------------------------+-----------------
c67112ccda3d4e39aae5bc1ffb171904 | deep         | temporal     | native              |               | query-binning-v1             | 1.7.2
```

**Les 22 captures Test_5 déjà terminées gardent leur snapshot original 1.7.1** :

```
decoder_version | count
----------------+-------
1.7.1           |    22
```

## Suite

Worker redémarré, va reprendre le job `queued` et traiter les 2 fichiers
`parcours_26Jun10_160230.2.nmf` et `.4.nmf` avec le décodeur 1.7.2
(fix `Stat.add` pour agrégations textuelles), puis populate_chain par
tranches (fix idle-in-tx 2026-10-28 08:34).
