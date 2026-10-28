# BC1 — nouvelle conception Light native (2026-10-28)

## Conception mesurée

- capture Deep : bins calculés directement sur `nmf_event_deep` ; aucune
  ligne dans `nmf_event_light_native`, donc surcoût natif nul ;
- capture Light : une ligne compacte par record source dans
  `nmf_event_light_native`, sans copie Deep ;
- valeurs et groupes : JSONB sparse, clé absente si valeur nulle ;
- types étroits : `system smallint`, `partial boolean`, raisons connues dans
  un masque `integer`, indices inconnus dans `smallint[]` ;
- position : uniquement les coordonnées GPS/POSI du record lui-même,
  transformées en EPSG:2154 et marquées `position_source='measured'`.

Migration Alembic : `bc1_light_native_sparse`, après
`bc1_import_measurement_lookup`. Le replay vide → head, le downgrade au parent,
puis le retour → head ont tous fini avec `exit=0`.

## G36 et corpus

```text
df -BG --output=avail /
40G
G36 free_gib=40
G36 VERDICT=PASS
```

```text
stat -c '%s %n' <trois NMF>
5078863  ...105812.8.nmf
9272163  ...105812.9.nmf
17040816 ...103519.3.nmf
```

Import applicatif historique, utilisé comme base comparable :

```text
G42 elapsed_s=246.431 files_running_max=3 child_processes_max=4 rss_peak_kb=2428836 idle_in_transaction_max_s=0.211
G42 statuses=['done', 'done', 'done'] nmf_files=3 distinct_sha=3 duplicate_files=0
G42 table=stg_event_raw rows=179178
G42 table=nmf_event_light rows=76012
G42 table=nmf_event_deep rows=0
G42 VERDICT=PASS
G42_EXIT=0
```

## Empreinte compacte

Mesure après `VACUUM (ANALYZE) nmf_event_light_native` :

| fichier | records natifs | octets logiques | moyenne octets/ligne | octets physiques alloués |
|---|---:|---:|---:|---:|
| 5 078 863 octets | 50 318 | 25 280 484 | 502,4 | 36 589 365 |
| 9 272 163 octets | 72 806 | 33 200 633 | 456,0 | 48 052 486 |
| 17 040 816 octets | 56 054 | 34 756 926 | 620,1 | 50 304 965 |

L'allocation physique par fichier est ventilée au prorata des octets
logiques ; le total physique vient directement de PostgreSQL :

```text
SELECT rel,pg_relation_size(rel::regclass),pg_indexes_size(rel::regclass),
       pg_total_relation_size(rel::regclass) ...
nmf_event_light        heap=38584320 index=19234816 total=60317696
nmf_event_light_group  heap=88014848 index=90079232 total=178151424
nmf_event_light_native heap=90439680 index=36716544 total=134946816
```

Les colonnes sparse sont effectivement absentes :

```text
values_null=19070 groups_null=130686 reason_extra_null=167614
unknown_null=96179 measured_position=1645
```

Calcul collé :

```text
awk 'BEGIN{source=5078863+9272163+17040816;compact=134946816;
historical=60317696+178151424;ratio=compact/source;
printf "compact_over_source=%.3f compact_vs_historical=%.3f saving_pct=%.2f%%\n",
ratio,compact/historical,(1-compact/historical)*100;
light=24*64*1024*1024*ratio/1024/1024/1024;
printf "Test5_deep_incremental_gib=0.00 equivalent_light_24x64MiB_gib=%.2f free_after_light_gib=%.2f\n",
light,40-light}'
compact_over_source=4.299 compact_vs_historical=0.566 saving_pct=43.41%
Test5_deep_incremental_gib=0.00 equivalent_light_24x64MiB_gib=6.45 free_after_light_gib=33.55
```

Pour Test_5 Deep, le surcoût de cette conception est donc exactement nul :
les bins liront le Deep existant. Pour un projet Light de 24 fichiers de
64 MiB, l'extrapolation mesurée est 6,45 GiB et reste au-dessus du garde de
20 GiB libres sur la référence à 40 GiB.

## Gardes

Le premier G39 a quitté avec `exit=1` sur une sérialisation Python de
`Decimal`, puis le premier témoin spatial avait zéro position mesurée. Ces
deux écarts ont été fermés : conversion de sortie explicite et lecture des
colonnes GPS/POSI prouvées par NFF, sans héritage.

```text
G38 captures=[
  {capture_id:0a6f9d273fd5,n:72806,seq_start:1,seq_end:73869},
  {capture_id:257357604ad1,n:56054,seq_start:1,seq_end:57827},
  {capture_id:5d9f19607366,n:50318,seq_start:1,seq_end:51455}]
G38 VERDICT=PASS
G39 temporal_delta_s=0.001 bad=0 binned=179178 outside=0 population=179178
G39 temporal_delta_s=0.01  bad=0 binned=179178 outside=0 population=179178
G39 temporal_delta_s=0.1   bad=0 binned=179178 outside=0 population=179178
G39 temporal_delta_s=1.0   bad=0 binned=179178 outside=0 population=179178
G39 spatial_50m bad=0 binned=1645 outside=177533 population=179178
G39 VERDICT=PASS
G38_G39_EXIT=0
```

Chaque agrégat inclut `capture_id` dans son `GROUP BY`; aucune fusion
inter-captures. `seq_start=min(seq)` et `seq_end=max(seq)` sont calculés dans
chaque bin. Les lignes sans position restent hors bin avec l'absence de
`position_source`; aucune interpolation.

## Héritage capture-local du fix précédent

Configuration : `BC4_SPATIAL_FIX_MAX_GAP_S`, défaut 1,0 s. Le dernier fix
est maintenu dans un état recréé pour chaque capture. Un fix porte
`position_source=exact` et `position_gap_s=0`; un record dans la fenêtre
porte `previous_fix` et l'écart absolu. Au-delà, aucune position n'est
stockée et `position_reason=fix_gap_exceeded`.

```text
awk 'BEGIN{n=179178;before=1645;after=168311;
printf "before_pct=%.3f after_pct=%.3f gain_points=%.3f outside_pct=%.3f\n",
100*before/n,100*after/n,100*(after-before)/n,100*(n-after)/n}'
before_pct=0.918 after_pct=93.935 gain_points=93.017 outside_pct=6.065
```

```text
G39 spatial_50m={bad:0,binned:168311,gap_violations:0,
 inheritance_without_same_capture_fix:0,n_exact:1645,n_inherited:166666,
 outside:10867,population:179178}
G39 inherited_gap_distribution_s={n:166666,p50:0.501,p90:0.911,
 p95:0.956,p99:0.991,max_gap:1.0}
G39 VERDICT=PASS
G38_G39_EXIT=0
```

Le taux binné passe donc de 0,918 % à 93,935 %. Aucun record hérité ne
dépasse le plafond et aucun ne précède le premier fix exact de sa capture.

## Requêtes vues/KPI

`app/kpi/nmf_bins.py` applique une projection unique :

- Deep : valeur et fixes lus directement dans `nmf_event_deep`; une fenêtre
  partitionnée par `(project_id,capture_id)` propage uniquement l'identifiant
  du dernier fix ;
- Light : valeur sparse et position lues dans `nmf_event_light_native`;
- temporel : 1/10/100 ms ou 1 s, médiane des valeurs numériques ;
- spatial : 10/25/50/100 m en EPSG:2154, médiane, `n_exact` et
  `n_inherited` ;
- paramètres absents : snapshot immuable de la capture.

La route KPI est
`/projects/{project}/captures/{capture}/kpi/{code}/bins`. La route
superstream traite chaque membre séparément et renvoie l'ordre
`(position,capture_id,seq)`; elle ne fusionne jamais deux captures.

Le premier plan Deep utilisait un `LATERAL` rescannant les fixes pour chaque
record. Le runner jetable a été arrêté (`exit=137`), puis l'écart a été fermé
par la fenêtre capture-local en un passage.

```text
G45 light project=g45-light-ba34f4d0 capture=eebf5c3bef7b snapshot=temporal/10ms records=50318 bins=5099
G45 deep project=g45-deep-ba34f4d0 snapshot=spatial/50m captures=[(b930aefc6bf8,43,25443),(eebf5c3bef7b,40,50318)]
G45 superstream=g45-ss-ba34f4d0 members=[(0,b930aefc6bf8),(1,eebf5c3bef7b)] order=position,capture_id,seq
G45 VERDICT=PASS
G45_EXIT=0
```

G42 final sur le chemin applicatif Light natif :

```text
G42 elapsed_s=96.830 idle_in_transaction_max_s=0.000
G42 statuses=['done'] nmf_files=1 distinct_sha=1 duplicate_files=0
G42 table=stg_event_raw rows=50318
G42 table=nmf_event_light rows=0
G42 table=nmf_event_light_native rows=50318
G42 table=nmf_event_deep rows=0
G42 VERDICT=PASS
G42_NATIVE_EXIT=0
```

Tests :

```text
pytest -q tests/test_nmf_native.py tests/test_nmf_decoder.py \
 tests/test_import_jobs.py tests/test_reparse_capture_script.py
.............................. [100%]
PYTEST_DECODER_IMPORT_EXIT=0

pytest -q tests/test_kpi_timeseries_unit.py tests/test_metrics_v3.py \
 tests/test_kpi_operator_population.py
............... [100%]
PYTEST_KPI_EXIT=0
```

Type SemVer : **minor back**. Release décodeur : **1.8.0**, documentée
dans `CHANGELOG_DECODER.md`. Le numéro de release applicative reste attribué
au merge par BC3 ; `pyproject.toml` n'est pas modifié.

Replay final Alembic : une première tentative de downgrade est restée en
attente d'un verrou conservé par le plan `LATERAL` G45 interrompu ; la révision
est restée à `bc1_light_native_sparse`. Sans kill de processus, seule la base
jetable a été arrêtée/redémarrée. Le replay suivant ferme l'écart :

```text
alembic downgrade bc1_import_measurement_lookup
exit=0
alembic upgrade head
Running upgrade bc1_import_measurement_lookup -> bc1_light_native_sparse
exit=0
```
