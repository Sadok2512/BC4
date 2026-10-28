# BC1 — vitesse d'ingestion (2026-10-28)

Périmètre : branche `feat/import-throughput`, worktree
`/home/devmat/BC4/back-bc1-ingest-speed`, compose jetable
`bc1-ingest-speed`, base `bc4_bench`. Aucune commande applicative ou SQL sur
la production.

## Environnement et écarts ouverts

Commande :

```text
nproc; free -m
```

Sortie :

```text
10
Mem: total=15987 used=4427 free=742 shared=1419 buff/cache=10816 available=9802
Swap: 0 0 0
```

Le fichier de référence `parcours_26Jun10_160230.1.nmf` (64 Mo) n'est pas
présent sous `/home/devmat`, `/mnt`, `/srv`, `/opt` ou `/tmp`. La référence
production fournie reste donc la mesure avant autoritaire : 529 339 records en
1 152 s, soit 459,496 records/s. Le profil ci-dessous utilise le plus petit
vrai NMF disponible (5 078 863 octets). L'estimation des onze fichiers Test_5
reste conditionnelle faute de leurs tailles accessibles.

G36 était PASS avant la création de `bc4_bench` (40,48 GiB libres). Une
tentative ultérieure de créer une seconde base a été refusée :

```text
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
G36_DISK ... free_gib=19.01 threshold_gib=20 verdict=FAIL
G36_BEFORE_FINAL_DB_EXIT=1
```

## Profil Deep cProfile

Commande (un fichier, un processus fichier) :

```text
docker compose -p bc1-ingest-speed -f docker-compose.bench.yml run --rm --no-deps \
  -e G42_EPHEMERAL_DB=YES -e G42_LEVEL=deep -e G42_IDLE_MAX_S=1.0 \
  -e G42_PROFILE=YES -e BC4_IMPORT_PROFILE=YES \
  -e 'G42_NMF_PATHS=/witness-nmf/Mesures Dynamiques - Incar/BCNE 26S24_VD_T_MESURE-BENCH-CENTRE-COMMERCIAL-PETITE-FORET_incar_26Jun11_105812.8.nmf' \
  runner python scripts/guards_2026_10/G42_parallel_import.py
```

Résultat processus fichier : total 497,716 s ; PostgreSQL exclusif 6,622 s
(1,33 %) ; Python/autre 98,67 %. Top 15 cumulatif :

| rang | appels | fonction | cumul s |
|---:|---:|---|---:|
| 1 | 1 | `ingest_upload` | 498,277 |
| 2 | 1 | `decode_capture` | 468,725 |
| 3 | 118 | `copy_rows` | 324,587 |
| 4 | 1 | `write_light` | 109,140 |
| 5 | 670505 | psycopg `write_row` | 73,237 |
| 6 | 670505 | psycopg `_copy_base.write_row` | 70,170 |
| 7 | 94842534 | `list.append` | 50,423 |
| 8 | 94413441 | `dict.get` | 49,830 |
| 9 | 50319 | `source.records` | 48,065 |
| 10 | 50318 | `decoder.decode` | 45,479 |
| 11 | 50319 | `read_deep` | 45,336 |
| 12 | 376257 | `array.dump` | 44,662 |
| 13 | 376257 | `array.dump_list` | 42,176 |
| 14 | 89742106 | `isinstance` | 38,538 |
| 15 | 50318 | `Light.add` | 34,813 |

Verdict du profil : G42 PASS, exit 0, elapsed 544,691 s, pic 905 648 KiB,
inactivité transactionnelle maximale 0,920 s.

## Mesures

Calculs collés :

```text
awk 'BEGIN { printf "ONE_LIGHT_RPS=%.3f\n",50318/70.476;
printf "REF_DEEP_RPS=%.3f\n",529339/1152;
printf "SIX_SEQ_RPS=%.3f\n",222215/1188.378;
printf "SIX_PAR_RPS=%.3f\n",222215/290.697;
printf "SPEEDUP=%.3f\n",1188.378/290.697;
printf "SIX_DEEP_RPS=%.3f\n",222215/355.350 }'
ONE_LIGHT_RPS=713.974
REF_DEEP_RPS=459.496
SIX_SEQ_RPS=186.990
SIX_PAR_RPS=764.421
SPEEDUP=4.088
SIX_DEEP_RPS=625.341
```

| cas | niveau | fichiers actifs max | temps total s | records/s | pic RSS KiB | idle max s | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| référence production fournie, un parcours 64 Mo | Deep | 1 | 1152,000 | 459,496 | non mesuré ici | non mesuré ici | référence |
| un vrai NMF, COPY après | Light | 1 | 70,476 | 713,974 | 695752 | < 1 | PASS |
| six vrais NMF, séquentiel avant index | Light | 1 | 1188,378 | 186,990 | 1075784 | 1,867 | FAIL |
| six vrais NMF, parallèle final | Light | 6 | 290,697 | 764,421 | 4755360 | 0,294 | PASS |
| six vrais NMF, parallèle (mesure Deep de calibration) | Deep | 6 | 355,350 | 625,341 | 4919504 | 50,212 avant pagination | FAIL puis fermé par pagination |

Le gain end-to-end six fichiers Light est 4,088×. Pour onze fichiers ayant la
même densité et le même nombre de records que la référence, l'extrapolation
Deep conditionnelle est :

```text
11 * 529339 / 625.341 = 9311.3 s = 155.2 min
```

Cette valeur n'est pas une prédiction ferme de Test_5 : les onze tailles et
nombres de records sources ne sont pas accessibles.

Facteurs mémoire mesurés sur six vrais NMF de 5 078 863 à 7 646 305 octets :
Light max 138,986× (défaut prudent 141×), Deep max 142,844× (défaut prudent
146×). Source inscrite dans `app/config.py`.

## G42 avant correction — FAIL complet

Commande : même garde, deux premiers NMF, image pré-correction.

```text
G42 database=bc4_bench project_id=g42-106db0819bc8 job_id=5a74c8813d7d47da81cb2bbfef398707
G42 elapsed_s=191.566 parallel_processes_max=3 rss_peak_kb=1581476 idle_in_transaction_max_s=77.942
G42 statuses=['done', 'done'] nmf_files=2 distinct_sha=2 duplicate_files=0
G42 table=stg_event_raw sha256=09f2623e075a5cee41899a56430bcf88e7f44983df07d17804f559ee4003243d rows=75761
G42 table=nmf_event_light sha256=8c299ad3022b584223c61bb2131bfce804ce0e7e805f5bb1279272b7417bc9c7 rows=39454
G42 table=nmf_event_deep sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 rows=0
G42 table=nmf_cell_second sha256=0912c99d6fd4ef86fa8c89cbba855b120a9f871852d4cdbec015020c63520663 rows=237046
G42 VERDICT=FAIL
G42_PRE_FIX_EXIT=1
```

Les quatre empreintes ont été recalculées en lecture seule sur le projet
pré-correction conservé ; les autres lignes sont la sortie originale.

## G42 final — PASS complet

```text
G42 database=bc4_bench project_id=g42-0c4ceaf19d90 job_id=8deefc408ee14b78a4518c29fc20af51
G42 elapsed_s=290.697 files_running_max=6 child_processes_max=7 rss_peak_kb=4755360 idle_in_transaction_max_s=0.294
G42 statuses=['done', 'done', 'done', 'done', 'done', 'done'] nmf_files=6 distinct_sha=6 duplicate_files=0
G42 table=stg_event_raw sha256=2ba50cbbd92e4f70da8856e6bf8b984fab9113c50a5278ba87d95aa197b46c7b rows=222215
G42 table=nmf_event_light sha256=5c679b186fc99c21c84da2ec6aaaf8b5f6aeb1915c42a2c36d69fb419b1f9252 rows=117672
G42 table=nmf_event_deep sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 rows=0
G42 table=nmf_cell_second sha256=c1d3a4317e111f02b45f2bae5bf8e3d3fd29fb77d2d8aa6b601685113508dbdf rows=714258
G42 VERDICT=PASS
G42_SIX_LIGHT_STATE_CHANGE_EXIT=0
```

Scénario corruption : G42 PASS, exit 0, statuts `['error', 'done']`, cause
`queued_source_sha_mismatch`, un seul fichier persistant, zéro doublon.

Scénario cgroup 1 GiB : G42 PASS, exit 0, pic 792 408 KiB, un fichier `done`,
aucun OOM. Le compose de banc impose aussi au plus 8 cœurs (`nproc - 2`).

## Non-régression

```text
pytest ciblé : 68 passed ; exit 0
G29_VERDICT PASS captures=1 divergences=0 ; exit 0
G32_VERDICT PASS total_differ=0 total_orphans_pair=0 total_orphans_proc=0 ; exit 0
G40_VERDICT PASS capture_count=3 ; exit 0
G40F_VERDICT PASS timeout=5min idle_max=1.182 ; exit 0
  sliced=monolithic sha256 20388573... rows=24012 duplicates=0
  interruption=reprise sha256 dec0be66... rows=21816 duplicates=0
G41_VERDICT PASS members=3 rowcount=132459 boundaries=3 ; exit 0
```

Le chemin séquentiel de production présent dans `main` avait bien le même
motif : commit expirant l'ORM dans `import_worker.py:39-60`, transaction ouverte
avant CPU dans `ingest/nmf.py:484-526`, et branches Deep/Light rouvertes avant
calcul dans `nmf_decoder/store.py:51-68,97-115`. L'audit était strictement en
lecture seule ; aucune production n'a été modifiée.

## Complément final après rebase BC3 `b1c2ce5`

G36 immédiatement avant la recréation du banc :

```text
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
G36_DISK path=/ free_bytes=41352253440 free_gib=38.51 threshold_bytes=21474836480 threshold_gib=20 verdict=PASS
G36_PRE_BENCH_EXIT=0
```

### Débits

Calcul collé :

```text
awk 'BEGIN { printf "COPY_BEFORE_RPS=%.3f\n",50318/98.412;
printf "COPY_AFTER_RPS=%.3f\n",50318/99.159;
printf "COPY_DELTA_PCT=%+.3f\n",100*((50318/99.159)/(50318/98.412)-1);
printf "MIX_SEQ_RPS=%.3f\n",131815/407.627;
printf "MIX_PAR_RPS=%.3f\n",131815/261.686;
printf "MIX_SPEEDUP=%.3f\n",407.627/261.686;
printf "SEQ_PEAK_MIB=%.3f\n",1968092/1024;
printf "PAR_PEAK_MIB=%.3f\n",2697856/1024 }'
COPY_BEFORE_RPS=511.299
COPY_AFTER_RPS=507.448
COPY_DELTA_PCT=-0.753
MIX_SEQ_RPS=323.372
MIX_PAR_RPS=503.714
MIX_SPEEDUP=1.558
SEQ_PEAK_MIB=1921.965
PAR_PEAK_MIB=2634.625
```

| mesure | fichiers | actifs max | temps total s | records/s | pic RSS MiB | idle max s | verdict / exit |
|---|---:|---:|---:|---:|---:|---:|---|
| même NMF 5 078 863 octets, avant COPY (base BC3 `b1c2ce5`) | 1 | 1 | 98,412 | 511,299 | 671,516 | 5,297 | FAIL / 1 (inactivité historique) |
| même NMF, après COPY et transactions courtes | 1 | 1 | 99,159 | 507,448 | 774,254 | 0,000 | PASS / 0 |
| lot court Light séquentiel | 3 | 1 | 407,627 | 323,372 | 1 921,965 | 0,050 | PASS / 0 |
| même lot Light parallèle | 3 | 3 | 261,686 | 503,714 | 2 634,625 | 0,048 | PASS / 0 |
| référence production fournie, parcours 64 Mo Deep | 1 | 1 | 1 152,000 | 459,496 | 4 300,800 | non fourni | référence |

COPY seul est neutre dans le bruit sur ce petit fichier end-to-end (`-0,753 %`).
Le gain mesuré du lot court est `1,558×` et vient principalement du pool de
processus. La chronologie parallèle, dérivée des trois `worker_elapsed_s`
persistés, est : 3 fichiers de 0 à 75,900 s ; 2 de 75,900 à 78,003 s ; 1 de
78,003 à 192,367 s ; puis 0 fichier pendant la finalisation unique jusqu'à
261,686 s. Commande source :

```text
SELECT f->>'filename',f->>'worker_peak_rss_mb',f->>'worker_elapsed_s'
FROM nmf_import_jobs j
CROSS JOIN LATERAL jsonb_array_elements(j.files::jsonb) f
WHERE j.id='2499916d84104f1db652d66f2141db7e'
ORDER BY (f->>'worker_elapsed_s')::numeric;
...105812.8.nmf|668.77734375|75.89979412899993
...104724.6.nmf|770.22265625|78.00320922699757
...103519.3.nmf|1816.7265625|192.3670389229992
```

### Modèle mémoire affine

Le modèle final commun Deep/Light est :

```text
RSS_estimée_MiB = 1370 + 46 * taille_MiB
```

Il est une enveloppe d'admission, pas une régression moyenne : il ne
sous-estime aucun témoin et ramène le gros fichier de 64 MiB à 4 314 MiB au
lieu des quelque 9 GiB du facteur 146×. Calcul complet collé :

```text
awk 'BEGIN { base=1370; k=46; # mêmes données que le tableau ci-dessous
  p=base+k*67108864/1048576; printf "prod64 predicted=%.3f\n",p }'
prod64 predicted=4314.000
```

| niveau | taille octets | RSS mesurée MiB | modèle MiB | erreur |
|---|---:|---:|---:|---:|
| Deep | 5 078 863 | 691,875 | 1 592,805 | +130,216 % |
| Deep | 6 076 126 | 800,465 | 1 636,554 | +104,450 % |
| Deep | 6 306 369 | 818,949 | 1 646,654 | +101,069 % |
| Deep | 6 703 712 | 880,848 | 1 664,085 | +88,919 % |
| Deep | 6 802 128 | 890,551 | 1 668,403 | +87,345 % |
| Deep | 7 646 305 | 985,410 | 1 705,436 | +73,069 % |
| Deep | 17 040 816 | 2 111,117 | 2 117,564 | +0,305 % |
| Deep production fourni | 67 108 864 | 4 300,800 | 4 314,000 | +0,307 % |
| Light | 5 078 863 | 670,211 | 1 592,805 | +137,657 % |
| Light | 6 076 126 | 771,164 | 1 636,554 | +112,219 % |
| Light | 17 040 816 | 1 818,137 | 2 117,564 | +16,469 % |

### Migration `bc1_import_measurement_lookup`

Contenu : index B-tree non unique sur
`measurement_points(project_id, capture_id, seq)`. Il sert les pages keyset de
la finalisation dans l'ordre canonique et évite un tri plein à chaque tranche.
Le downgrade supprime uniquement cet index.

Replay base vide → head → retour :

```text
alembic upgrade head
REV=bc1_import_measurement_lookup
INDEX=CREATE INDEX ix_measurement_points_project_capture_seq ON public.measurement_points USING btree (project_id, capture_id, seq)
alembic downgrade 0063_merge_import_superstream
REV=0063_merge_import_superstream
INDEX_COUNT=0
ALEMBIC_REPLAY_EXIT=0
```

### Gardes post-rebase

Le premier G42 Deep moyen a exposé l'écart puis le petit témoin a fermé le
même chemin après réduction des pages Deep de 1 000 à 100 séquences :

```text
G42_MEDIUM_DEEP_AFTER_FIX_EXIT=1
G42 elapsed_s=436.914 idle_in_transaction_max_s=1.289
G42 VERDICT=FAIL

G42 elapsed_s=193.816 files_running_max=1 child_processes_max=2
rss_peak_kb=816484 idle_in_transaction_max_s=0.409
G42 statuses=['done'] nmf_files=1 distinct_sha=1 duplicate_files=0
G42 VERDICT=PASS
G42_SMALL_DEEP_PAGE100_EXIT=0
```

G44 post-rebase :

```text
[G44] frozen captures (done, pas remises en file): 1 identifiées, 1 inchangées (snapshot + comptes + decoded_at)
[G44] requeued captures (fichier remis en file): 1 identifiées, decoded_at vérifié avancé
G44_VERDICT PASS frozen=1 new=0 fails=0
G44_POST_REBASE_EXIT=0
```

Suite ciblée finale : la première exécution locale avec DSN volontairement
invalide a correctement échoué sur les deux tests PostgreSQL (`exit=1`). La
même sélection sur `bc4_bench` jetable ferme l'écart :

```text
pytest -q tests/test_import_admission.py tests/test_import_jobs.py \
  tests/test_nmf_decoder.py tests/test_populate_atomic.py \
  tests/test_reparse_capture_script.py \
  tests/test_requeue_import_decoder_172_failures.py \
  tests/test_requeue_import_schema_failures.py
.................................... [100%]
FINAL_INGEST_TEST_DB_EXIT=0
```
