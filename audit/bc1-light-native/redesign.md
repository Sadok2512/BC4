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
