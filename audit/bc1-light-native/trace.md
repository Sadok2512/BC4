# BC1 — Light natif et bins à la requête (2026-10-28)

Périmètre : branche `feat/import-throughput`, projet Docker jetable
`bc1-lot-b-estimate`, aucune lecture ni écriture en production.

## G36 et banc

```text
nproc
10
df -BG --output=avail /
40G
G36 free_gib=40
G36 VERDICT=PASS
```

Le premier `alembic upgrade head` a échoué avec `exit=1` (`connection
refused`) avant que PostgreSQL soit healthy. Après `docker inspect` =
`healthy`, le replay vide → head a réussi avec `exit=0`, jusqu'à
`bc1_import_measurement_lookup`.

Import applicatif Light de trois vrais NMF, `BC4_BENCH_CPUS=8`
(`nproc - 2`) :

```text
G42 elapsed_s=224.557 files_running_max=3 child_processes_max=4 rss_peak_kb=2428284 idle_in_transaction_max_s=0.279
G42 statuses=['done', 'done', 'done'] nmf_files=3 distinct_sha=3 duplicate_files=0
G42 table=stg_event_raw rows=179178
G42 table=nmf_event_light rows=76012
G42 VERDICT=PASS
G42_EXIT=0
```

## Audit du stockage actuel

`app/nmf_decoder/light.py:59-110` regroupe aujourd'hui par
`(event_code, system, floor(t_rel_s), dimensions)` ; `seq`/`seq_last`
délimitent donc une plage et `n_records` porte la population agrégée.
`app/nmf_decoder/store.py:91-116` écrit ces buckets dans
`nmf_event_light` et leurs groupes dans `nmf_event_light_group`.

Lecteurs runtime identifiés :

- catalogue et disponibilité : `app/kpi/metrics_catalog_v4.py:113-332`,
  `app/kpi/metrics_catalogue_v6.py:133`, `app/kpi/metrics_v3.py:138-285` ;
- populations/KPI : `app/kpi/nmf.py:31-32`, `app/kpi/population.py:74`,
  `app/kpi/service_v2.py:116-461`, `app/nmf_decoder/projection.py:19-85` ;
- séries et API : `app/routes/kpi_timeseries.py:351-429`,
  `app/routes/metrics.py:441-474`, `app/routes/nmf_decode.py:123` ;
- signalisation/radio : `app/signaling/service.py:40-315`,
  `app/signaling/rf.py:18-44`, `app/services/task_run.py:111` ;
- cellules et classification : `app/nmf_decoder/cells.py:34`,
  `app/nmf_decoder/store.py:220`.

Le contrat cible devra faire lire à ces consommateurs une projection de bins
calculée par requête. Les lectures d'occurrence pourront lire le natif ; les
KPI temporels devront demander explicitement leur résolution et ne plus
interpréter une ligne Light comme une seconde préagrégée.

## Estimation disque bloquante

Mesure logique par capture (`sum(pg_column_size(row))`) :

| taille source | records | lignes Light actuelles | facteur lignes natif | facteur heap estimé |
|---:|---:|---:|---:|---:|
| 5 078 863 | 50 318 | 24 783 | 2,030 | 2,083 |
| 9 272 163 | 72 806 | 21 348 | 3,410 | 2,765 |
| 17 040 816 | 56 054 | 29 881 | 1,876 | 1,821 |

Tailles physiques mesurées :

```text
nmf_event_light       heap=38649856 index=19234816 total=60383232
nmf_event_light_group heap=88014848 index=90079232 total=178151424
```

Projection native : 179 178 lignes Light et 1 405 049 lignes de groupes,
soit 246,7 MiB logiques. Le ratio physique/logique mesuré vaut 1,934 ; la
projection physique est donc 500 150 999 octets pour 31 391 842 octets de
fichiers source, soit ×15,933.

Calcul collé :

```text
awk 'BEGIN{sample_source=31391842;physical=238534656;logical=123353417;
native_logical=258643066;overhead=physical/logical;
native_physical=native_logical*overhead;ratio=native_physical/sample_source;
test5_source=24*64*1024*1024;test5_gib=test5_source*ratio/1024/1024/1024;
printf "native_over_source=%.3f test5_gib=%.2f free_after=%.2f\n",
ratio,test5_gib,40-test5_gib}'
native_over_source=15.933 test5_gib=23.90 free_after=16.10
LOT_B_DISK VERDICT=FAIL
LOT_B_DISK_EXIT=1
```

Les 24 captures Test_5 sont prouvées par
`audit/ops-20261028-test5-legacy-snapshot/trace.md` (22 terminées + 2 en
attente). Le chemin et les tailles exactes du corpus source ne sont pas
accessibles à BC1. L'extrapolation utilise donc la seule référence Test_5
fournie, 64 MiB. Elle fait passer l'espace libre sous le plancher de 20 GiB.

**VERDICT DISQUE=FAIL (exit 1).** Conformément à l'ordre, le développement
du lot B s'arrête avant toute modification du décodeur. L'écart reste ouvert
jusqu'à fourniture par BC3 des tailles exactes, ou mise à disposition d'un
volume suffisant. G38 et G39 ne sont pas annoncés : aucun garde sans témoin
n'est déclaré PASS.
