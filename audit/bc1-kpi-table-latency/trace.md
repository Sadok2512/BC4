# bc1/kpi-table-latency — preuve par contenu

## Identité CELLMEAS

Commande :

```sql
SELECT system,cell_type,count(*) groups,
 count(*) FILTER (WHERE cell_pci IS NULL) pci_null,
 count(*) FILTER (WHERE cell_ch IS NULL) arfcn_null,
 count(DISTINCT (cell_ch,cell_pci)) FILTER
   (WHERE cell_ch IS NOT NULL AND cell_pci IS NOT NULL) physical_cells
FROM nmf_event_light_group g JOIN nmf_event_light l
  USING(project_id,capture_id,seq)
WHERE g.project_id='43e81a34a073' AND l.event_code='CELLMEAS'
  AND g.group_name='cells'
GROUP BY system,cell_type ORDER BY system,cell_type;
```

Résultat Test_6 : 42 630 groupes voisins (`LTE 1/2`, `NR 1000`) ;
`pci_null=0`, `arfcn_null=0`. L'identité physique retenue sur ce corpus est
donc `(système, ARFCN, PCI)`. Exemple exact : capture `a4b0c321c52e`, seq 23,
type 2, PCI 196, ARFCN 1675. Deux occurrences de la même cellule portent des
poids 2 et 1 ; la ligne physique conserve `observation_count=2` et calcule la
moyenne pondérée, sans déduplication silencieuse.

## Feuilles avant/après

Commande avant (image live 0.97.2, lecture seule) :

```text
docker exec bc4-api-1 python -c '<build_catalog_v4 Test_6 puis filtre
source_column=cell_rsrp et label neighbour>'
```

Résultat : `BEFORE_NEIGHBOUR_LEAVES 65` : Listed LTE 2 occurrences,
Detected LTE 42 occurrences, Listed NR 21 occurrences.

Commande après (code de branche monté, même DB en lecture seule) :

```text
docker run --rm --network bc4_default ... python -c
'<build_catalog_v4 Test_6 et même filtre>'
```

Résultat : `NEIGHBOUR_LEAVES 3` : Listed LTE, Detected LTE, Listed NR ;
sélections `cell_rsrp@lte-type-1`, `cell_rsrp@lte-type-2`,
`cell_rsrp@nr-type-1000`.

## Banc jetable et conservation

Commande G36 avant création :

```text
python3 /home/devmat/BC4/scripts/_guard_G36_disk.py
```

Résultat : `free_gib=67.59`, `verdict=PASS`, exit 0. Base
`bc1_kpi_latency`, migration head `0067_kpi_physical_cell_indexes`. Sous-ensemble
copié par `COPY ... TO STDOUT | COPY ... FROM STDIN` : 27 585 lignes
`nmf_cell_second` RSRP detected et 27 585 groupes d'identité exacts.

Commande de conservation G25.4 :

```sql
SELECT sum((n->>'n')::bigint) semantic_leaf_sum,
       count(DISTINCT (capture_id,second,cell_index)) projected_total
FROM metrics_catalog_cache ... JOIN nmf_cell_second ...;
```

Résultat : `semantic_leaf_sum=27585`, `projected_total=27585`, PASS.

## Latence

Avant, commande de service avec le code 0.97.2 monté, `table_only=true`, page
25 et evidence neutralisée en lecture seule :

```text
Dataset(...).response([cell_rsrp@lte-type-2],page=1,page_size=25,table_only=True)
```

Résultat avant optimisation : `DATASET_INIT_S=18.901251`,
`RESPONSE_S=1.196682`, `TOTAL_S=20.097934`.

Après, même commande sur `bc1_kpi_latency` migrée :

```text
AFTER_RESPONSE_S 0.765959
ROWS 25 TOTAL_ROWS 21079 TOTAL_PAGES 844
IDENTITY_NULL_ROWS 0
LATENCY_VERDICT PASS
```

`EXPLAIN (ANALYZE, BUFFERS)` de la requête page + total :
`Execution Time: 330.146 ms`. La pagination est un `LIMIT 25 OFFSET 0` dans
la requête ; `COUNT(*) OVER()` fournit le total sans second scan.

Filtre exact : `cell_pci=196&cell_arfcn=1675` → `FILTER_TOTAL 1465`,
`FILTER_MISMATCH 0`, `FILTER_VERDICT PASS`.

## Gardes

```text
G25_VERDICT PASS ... cell_sum_loss=0
G25_EXIT=0
GC1 version=2.56.2
GC1 db_sha=f230c82442a0a2badfc2ee54bfca14dbaa95870a7547fcc90d0b6e76b7f3bb30
GC1 disk_sha=f230c82442a0a2badfc2ee54bfca14dbaa95870a7547fcc90d0b6e76b7f3bb30
GC1_VERDICT PASS
GC1_EXIT=0
```

Tests back ciblés : `pytest -q tests/test_metrics_v3.py` → 4 PASS après ajout
du sélecteur sémantique. Tests front ciblés sous Node 22 : 2 fichiers,
4 tests PASS. Le runner Bun isolé échoue avant collecte sur son chargement Zod,
mais le même Vitest et les mêmes dépendances passent sous Node. Le contrôle
TypeScript ne signale plus d'erreur dans les fichiers du lot ; il conserve les
erreurs opérateur historiques hors lot (`AssistantMap`, fixtures, overview).
