# BC1 — KPI table lean — preuve jetable 2026-10-29

Branche back : `bc1/kpi-table-lean`. Base exclusivement jetable :
`bc1_kpi_table_lean`. Aucune lecture ni écriture de production.

## G36 et fixture

Commande :

```sh
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
```

Sortie : `free_bytes=73650372608 free_gib=68.59 ... verdict=PASS`.

`scripts/guards_2026_10/G49_kpi_table_fixture.py` a importé en Deep le
témoin `parcours_26Jun10_155941.8.nmf` :

```text
G49 project_id=bc1-kpi-lean capture_id=a4b0c321c52e file_status=done
G49 VERDICT: PASS
```

## Endpoint avant/après (`curl -w`)

Même projet, capture et sélection `cell_rsrp@1003`. Le premier appel reproduit
le contrat complet historique (`page_size=5000`); le second active le contrat
table lean (`table_only=true`, `page_size=25`).

```text
BEFORE     http=200 size=3666149 time=20.695390
AFTER_LEAN http=200 size=16993   time=13.960951
```

Contenu après : `rows=25`, `total_rows=4857`, `total_pages=195`, `series=0`,
`histogram=0`. Première ligne cellule : `Serving · LTE`, `PCI 195`,
`ARFCN 1675`; index interne technique `1003`.

## GPS par contenu

Jointure exacte par `(project_id, capture_id, seq)` entre `stg_event_raw` et
`nmf_event_deep`, jamais par `ts` : 49 événements GPS réels arrondis à
`50.396927 / 2.971448`, de `t_rel_s=0` à `47.766`. Les premières lignes sont
les seq `19, 103, 220, 309...`, avec des fixes espacés autour d'une seconde.

La réponse table porte `gps_source=previous_fix`; sur les 4 857 lignes de
l'appel complet, `max(gps_age_s)=0.9960000000000946`. Sur la page lean,
`max(gps_age_s)=0.8739999999999988`. Il s'agit donc de fixes GPS réels
stationnaires, avec héritage inférieur à une seconde, pas d'une position
propagée au-delà d'une seconde.

## Catalogue avant/après

Commande de comparaison des JSON générés :

```text
2.56.0 CELLMEAS/MIMOMEAS leaves=1506
blocks={AMPS/NAMPS, EVDO, GSM, LTE, NR, TETRA, UMTS FDD,
        UMTS TD-SCDMA, WLAN, WiMAX, CDMA, iDEN}
2.56.1 CELLMEAS/MIMOMEAS leaves=270
blocks={LTE, NR}
```

Contrôle du payload servi final :

```text
WRONG_TECH_VISIBLE 0 CROSS_SYSTEM_MISMATCH 0
cell_rsrp@1003 RSRP (bloc LTE) @ Serving
cell_rsrp@9670 RSRP (bloc NR) @ SCG PSCell
cell_rsrp@9751 RSRP (bloc NR) @ Listed NR neighbour
```

Ainsi `Pathloss (bloc UMTS FDD)` est remplacé par sa feuille documentée
`Pathloss (bloc LTE)` pour le système LTE; `RxLev (bloc iDEN)` disparaît des
branches LTE/NR.

## Gardes

```text
G25_VERDICT PASS ... orphans=0 dup_node_ids=0 dup_metric_codes=0
false_grey=0 stale_false_grey=0 cell_sum_loss=0 grey_no_reason=0
GC1 version=2.56.1 spec=2.50 decoder_min=1.8.2
GC1 db_sha=a6bdeac20ed1a1af1b1570861de3f6de990192fd89e1e4ddc9291de935b9fc74
GC1 disk_sha=a6bdeac20ed1a1af1b1570861de3f6de990192fd89e1e4ddc9291de935b9fc74
GC1_VERDICT PASS
```

Tests ciblés : front `5 passed`; back `4 passed`.

Le lint ciblé sort non nul sur 432 écarts Prettier du fichier historique
`MetricsWorkspace.tsx`; écart déclaré, sans échec fonctionnel dans les tests
ciblés. `git diff --check` est PASS.
