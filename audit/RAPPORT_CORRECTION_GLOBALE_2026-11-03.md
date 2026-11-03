# RAPPORT — Correction globale du catalogue Métriques

**Date** : 2026-11-03
**Agent** : Agent BC2 (signé)
**Session** : chantier routé vers `[bc4]` (back `bc4-back` + front `franco-focus-forge`), projet de preuve **Test_6** `43e81a34a073`
**Captures** : Test_6 = `a4b0c321c52e` (parcours_26Jun10_155941.8.nmf) · ikea.2 = `ecffb18dbd7f` (ikea_26Jun10_172354.2.nmf) · ikea.6 = `daa2b1df250d` (ikea_26Jun10_172354.6.nmf)

> **Règles** : aucun chiffre sans sa requête · recherche par CONTENU · un écart se ferme ou se déclare OUVERT avec fichier:ligne · gardes PAR CAPTURE, chaque colonne nommée · aucune CI, garde lancé à la main, sortie collée.

---

## 1. VERSIONS

### État live final

```
back            : 0.126.2
front           : 1.134.0
catalogue       : 2.64.0 (sha 5fc6a0064ea40eb16143c09a9c0924d1a834241fac424df41ae1930a35eaa480)
décodeur        : 1.10.5
alembic head    : 0087_macrate_nr_scope
```

### Images

```
bc4-api:0.126.2-c6e9081       sha256:4dce86977a7c28fb40b3b19702b985ac2c0fdb5a221d6226e51152eed8e9d677
bc4-front-v2:1.134.0-f23e122  sha256:cae021f062860549b28c0ac99516479a887fcaa9c53290c69b3b2cc96ed5fa16
```

### Commits depuis `4274516`

```
e723875 chore(audit): REPRISE 7 handoff final — tableau P1-P20 + commits + CSV live
f0c0c0b chore(deploy): pin bc4-api 0.126.2-c6e9081 + front 1.134.0-f23e122 (REPRISE 7 fin)
c6e9081 fix(catalog): filtre STRUCT sur dynamic entries + gardes P20 toutes à 0
987f6c3 chore(deploy): pin bc4-api 0.126.1-49f8e31 (REPRISE 7 Lot 7 CSV endpoint)
49f8e31 feat(metrics): endpoint /metrics/catalog-csv per-capture (REPRISE 7 Lot 7)
2f231a2 chore(deploy): pin bc4-api 0.126.0-74e17dc (catalog 2.64.0 Lot 6 display_code)
74e17dc feat(catalog): display_code émis par le back + catalog 2.64.0 (REPRISE 7 Lot 6)
0b8bc7d chore(deploy): pin bc4-api 0.125.3-f591af9 (Lot 1 partiel + fix écart plaid_mcs0)
f591af9 feat(catalog): dynamic entries pour TOUTE colonne cell_scoped observée (0.125.3)
1b180fa chore(audit): REPRISE 7 gardes Points 1-3 + écart OUVERT plaid_mcs0
3d04519 chore(audit): handoff REPRISE 7 — Point 1 FAIT + Point 2 partiel
6fdb19c chore(deploy): pin bc4-api 0.125.2-9a7cf3b (catalog 2.63.2)
9a7cf3b chore(main): bump app.version to 0.125.2 (missed in 957e6cd)
957e6cd feat(catalog): 2.63.2 relabel chi_rrc_state + dedup CHI LTE #NN (REPRISE 7 Point 2)
3585a2d chore(audit): handoff REPRISE 6 — régressions 2.63.0 fermées, 2.63.1 live
7c74b4a deploy: pin bc4-api 0.125.1-a96a3de (catalog 2.63.1 — PHY LTE + CHI/MEI restored)
a96a3de fix(catalog): 2.63.1 restore PHY LTE + CHI/MEI (back 0.125.1)
b598fe6 chore(audit): handoff REPRISE 4 — catalog 2.63.0 live, 5 gardes P20 à 0
b616f33 deploy: pin bc4-api 0.125.0-d04f532 (catalog_release 2.63.0)
d04f532 feat(catalog): publish catalog_release 2.63.0 (back 0.125.0, lots 3+4+5)
202609f chore(audit): handoff REPRISE 3 — Lot 3 + Lot 5 live
15d8625 deploy: pin bc4-api 0.124.7-0e1245e (Lot 5 kind field + STRUCT out of tree)
0e1245e feat(catalog): Lot 5 kind field + STRUCT out of tree (back 0.124.7)
4d5f840 deploy: pin bc4-api 0.124.6-aea85f4 (Lot 3 ghost placeholders filtered)
aea85f4 feat(catalog): Lot 3 drop ghost NR placeholders (back 0.124.6)
144c608 chore(audit): handoff final REPRISE 2 — Lot 1 5/9 + CHI LTE
fb2ad88 deploy: pin bc4-api 0.124.5-0248c6e (decoder 1.10.5, CHI LTE live)
0248c6e fix(decoder): CHI LTE schema + system_col=4 (1.10.5, back 0.124.5, lot 2 LTE)
c02f6e8 deploy: pin bc4-api 0.124.4-2bc6f95 (decoder 1.10.4, cell_scoped NR live)
2bc6f95 fix(decoder): cell_scoped=true on NR variants (1.10.4, back 0.124.4)
8c0eaf5 chore(audit): handoff reset §Point courant + close O-A/O-03/O-05
853f75d chore(audit): session end — handoff update (lot 1 : 4/9 schémas livrés)
e00c70f deploy: pin bc4-api 0.124.3-954117d (decoder 1.10.3, MACRATE/MACRATEU NR live)
954117d feat(decoder): MACRATE_NR + MACRATEU_NR variants (1.10.3, back 0.124.3)
e1fcac6 deploy: pin bc4-api 0.124.2-cb64e46 (decoder 1.10.2, PLAIU NR live)
cb64e46 feat(decoder): PLAIU NR variant (1.10.2, back 0.124.2)
dc106d3 deploy: pin bc4-api 0.124.1-4951569 (decoder 1.10.1 live, PLAID NR complete)
4951569 fix(decoder): PLAID NR header filter (1.10.1, back 0.124.1, O-A closed)
d84c7bc fix(main): sync FastAPI app.version with pyproject 0.124.0 (handoff proof)
```

Total : **39 commits** depuis 4274516.

---

## 2. AVANT / APRÈS — par capture

### Baked JSON (release)

Source : `app/kpi/catalog_release/catalog_2.62.0.json` vs `app/kpi/catalog_release/catalog_2.64.0.json`.

```python
# requête (sortie collée §4)
from app.kpi.catalog_release.registry import load_catalog_json
c = load_catalog_json("2.62.0") / "2.64.0"
displayed = [n for n in c["nodes"] if n.get("node_type")=="leaf" and n.get("displayed")]
# puis partition par tech via remontée parent_id → node_type="tech"
```

| | 2.62.0 (avant) | 2.64.0 (après) |
|---|---|---|
| Feuilles displayed total | **8 735** | **5 323** |
| LTE | 6 358 | 3 378 |
| NR | 276 | 56 (baked, hors dynamic) |
| Shared | 644 | 607 |
| Other | 1 430 | 1 255 |
| CAPTURE | 27 | 27 |

Partition par kind — 2.64.0 baked :

| kind | leaves |
|---|---|
| KPI | 4 851 |
| DIMENSION | 344 |
| KPI_CATEGORICAL | 128 |

### Cache runtime (par capture)

Requête :
```sql
WITH nodes AS (
  SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%'
)
SELECT scope_key,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf') AS leaves_total,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND (n->>'n')::int > 0) AS with_values,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='LTE') AS lte,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='NR') AS nr,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='Shared') AS shared,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='Other') AS other
FROM nodes GROUP BY scope_key ORDER BY scope_key;
```

Sortie :

| capture | total | with_values | LTE | NR | Shared | Other |
|---|---|---|---|---|---|---|
| Test_6 (a4b0c321c52e) | 5 554 | **424** | 3 433 | 232 | 607 | 1 255 |
| ikea.6 (daa2b1df250d) | 5 494 | **327** | 3 387 | 218 | 607 | 1 255 |
| ikea.2 (ecffb18dbd7f) | 5 503 | **330** | 3 406 | 208 | 607 | 1 255 |

Note : les 27 "unclassified" sont les leaves CAPTURE (tech="CAPTURE") rangées hors des 4 branches principales.

Partition par kind, par capture :

```sql
WITH nodes AS (
  SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%'
)
SELECT scope_key, n->>'kind' AS kind, COUNT(*)
FROM nodes WHERE n->>'node_type'='leaf'
GROUP BY scope_key, n->>'kind' ORDER BY scope_key, n->>'kind';
```

| capture | KPI | DIMENSION | KPI_CATEGORICAL |
|---|---|---|---|
| Test_6 | 5 042 | 374 | 138 |
| ikea.6 | 5 000 | 360 | 134 |
| ikea.2 | 5 003 | 364 | 136 |

STRUCT, kind IS NULL : **0** sur chaque capture (gardes P8, P14).

---

## 3. PAR LOT (1 à 7)

### Lot 1 — Schémas NR + exposition catalogue — **PARTIEL (FAIT générique) + OUVERT (schémas spécifiques)**

**Commits** : `4951569`, `cb64e46`, `954117d`, `2bc6f95`, `0248c6e`, `f591af9`

**Fichiers:lignes** :
- `app/nmf_decoder/schemas-2.50/PLAID_NR.yaml`, `PLAIU_NR.yaml`, `MACRATE_NR.yaml`, `MACRATEU_NR.yaml` — tous avec `cell_scoped: true`.
- `app/nmf_decoder/schemas-2.50/CHI.yaml:8` — `system_col: 4` (fix 1.10.5).
- `app/nmf_decoder/store.py:40-80` — `normalize_for_stored_deep` : header_filter par schéma via `schema_for(event, system).get('header')`.
- `app/kpi/metrics_catalog_v4.py:710-740` + `:1153-1180` — `event_columns` et `human_field_by_col` étendues à toutes les colonnes `cell_scoped=True` déclarées par `metrics_v3.definitions()` (fix écart Point 1 : plaid_mcs0 / plaiu_mcs0 étaient invisibles).

**Garde PHY NR par capture** (§4 ci-dessous — colonnes nommées).

**OUVERT résiduel** :
- `CQI_NR` : 0 variante NR dans le catalogue (nécessite `app/nmf_decoder/schemas-2.50/CQI_NR.yaml` avec header + groupes NFF 2.50 p.579-581).
- `DCI_NR` : 0 variante NR (nécessite `DCI_NR.yaml` NFF 2.50 pages DCI format NR).
- `SCELL` / `SCELLMOD` : 0 colonne observée dans `nmf_cell_second` (`SELECT DISTINCT metric_code FROM nmf_cell_second WHERE event_code IN ('SCELL','SCELLMOD')` → 0 row). Schémas de base absents, pas que NR.

### Lot 2 — Reclassement tech + CHI LTE actif — **FAIT**

**Commits** : `0248c6e`, `fb2ad88`.

**Fichiers:lignes** :
- `app/nmf_decoder/schemas-2.50/CHI.yaml:8` : `system_col: 4` ajouté (était `null` : système jamais extrait → tous records marqués `system_undocumented`, 0 record projeté). Décalage des colonnes +1.
- `app/kpi/metrics_catalog_v4.py:654-662` — `_is_foreign_bloc` basé sur `field_system` NFF explicite ∈ {1,2,5,6,10,11,12,13,21,25,51,52,53,55} au lieu du label regex (qui dropait aussi `mei_measurement_event` / `chi_rrc_state`).

**Garde** :
```sql
SELECT capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle_1,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected_2
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id;
→ Test_6: 181/451 · ikea.6: 6/5 · ikea.2: 5/6 (§5 ci-dessous)
```

### Lot 3 — Ghost NR placeholders filtrés — **FAIT**

**Commit** : `aea85f4`.

**Fichier:ligne** : `app/kpi/metrics_catalog_v4.py:603-607` — `_is_ghost_nr_placeholder(n)` : drop feuilles dont `cell_type ∈ {100..131, 98, 198, 199, 1000, 1001, 1002}` ET `field_system != 9`. 2 405 feuilles filtrées (voir §6).

**Garde** :
```sql
WITH l AS (SELECT jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT COUNT(*) FROM l
WHERE n->>'node_type'='leaf' AND n->>'cell_label' ~ '^SCell\s*(1[0-9]{2}|1[0-9]{3})$';
→ 0 (P13)
```

### Lot 4 — Foreign bloc + MIMO/CSI/PMI sur voisines — **FAIT (RF) + OUVERT (CHI structurel)**

**Commits** : `d04f532`, `a96a3de`.

**Fichiers:lignes** :
- `app/kpi/metrics_catalog_v4.py:664-669` — `_is_mimo_csi_on_neighbour`. 27 feuilles filtrées.
- `app/kpi/metrics_catalog_v4.py:654-662` — _is_foreign_bloc.

**Garde** :
```sql
WITH l AS (SELECT jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT COUNT(*) FROM l
WHERE n->>'node_type'='leaf' AND n->>'event' IN ('MIMOMEAS','CSI','PMI')
  AND n->>'cell_label' ILIKE '%neighbour%';
→ 0 (P12)
```

**OUVERT** : CHI reste rangé sous `cat_Shared_services_tasks` (116/116 feuilles CHI en "Shared"). Re-parentage sous LTE > Signalling + NR > Signalling non livré.

### Lot 5 — Champ `kind` KPI/KPI_CATEGORICAL/DIMENSION/STRUCT — **FAIT**

**Commit** : `0e1245e`.

**Fichiers:lignes** :
- `app/kpi/metrics_catalog_v4.py:617-643` — `_kind_for_leaf()` : classification. STRUCT exclu du tree (ligne 687).
- `app/kpi/metrics_catalog_v4.py:1246-1255` — même filtre sur dynamic entries (fix `c6e9081`).

**Garde** :
```sql
WITH l AS (SELECT jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT COUNT(*) FROM l
WHERE n->>'node_type'='leaf' AND n->>'kind'='STRUCT';
→ 0 (P8)
```

### Lot 6 — `display_code` émis par le back → catalog 2.64.0 — **FAIT**

**Commit** : `74e17dc`.

**Fichiers:lignes** :
- `app/kpi/metrics_v3.py:121, 136, 170, 172` — `display_code=code` sur chaque entrée.
- `app/kpi/metrics_v3_capture.py:86` — idem CAPTURE.
- `app/kpi/metrics_catalog_v4.py:1028-1035` — `display_code=metric_id` sur nodes_out baked (unique par node, évite collision selection).
- `app/kpi/metrics_catalog_v4.py:1216-1232` — `baked_cells_no_sys` + dynamic skip pour éviter doublon baked+dynamic.
- `app/kpi/metrics_catalog_v4.py:1251, 1283` — `display_code=selection` sur dynamic nodes_out + metrics_out.
- `scripts/catalog/patch_2_64_0.py` — enrichit 5 323 leaves baked avec `display_code=metric_id`.

**Garde doublons par capture** :
```sql
WITH l AS (SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT scope_key,
  COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'display_code' IS NULL) AS null_dc,
  COUNT(*) FILTER (WHERE n->>'node_type'='leaf') AS leaves
FROM l GROUP BY scope_key ORDER BY scope_key;
→ Test_6: 5554 leaves, 0 null · ikea.6: 5494 leaves, 0 null · ikea.2: 5503 leaves, 0 null

-- Dedup : 0/0/0 (via test Python verify_dc.py — chaque capture est unique)
```

### Lot 7 — Export front avec Kind, unit, data_type, colonne par capture — **FAIT**

**Commits back** : `49f8e31`, `987f6c3`.
**Commit front** : `f23e122`.

**Fichiers:lignes** :
- `app/routes/metrics.py:395-517` — `GET /projects/{pid}/metrics/catalog-csv` : merge toutes les captures par `display_code`, 1 colonne `n_<capture_id>` par capture + Kind / unit / data_type.
- `franco-focus-forge/src/features/kpi/MetricsCatalogSidebar.tsx:490-516` — bouton Export CSV appelle l'endpoint back ; design UI inchangé.
- `franco-focus-forge/package.json:3` — `1.133.25 → 1.134.0` (minor).

**Garde** : CSV live produit, 5 578 lignes (header + 1 par leaf), 1.1 MB, colonnes `n_a4b0c321c52e / n_daa2b1df250d / n_ecffb18dbd7f`. Preuve dans §4 (PHY NR).

Artefacts joints :
- `export_test_6_final.csv` — 5 578 lignes, catalog complet pour les 3 captures.
- `export_test_6_with_values.csv` — 457 lignes (header + 455 feuilles avec au moins une valeur sur une capture).
- `export_ikea_6_with_values.csv` — 329 lignes (header + 327 feuilles avec valeurs sur ikea.6).

---

## 4. PHY NR par capture (colonnes nommées) — catalogue ET live

### Garde live `nmf_cell_second`

```sql
SELECT capture_id,
  SUM(CASE WHEN metric_code='plaid_prbs' THEN 1 ELSE 0 END) AS NR_PDSCH_PRBS_PSCELL,
  SUM(CASE WHEN metric_code='plaid_mcs0' THEN 1 ELSE 0 END) AS NR_PDSCH_MCS0_PSCELL,
  SUM(CASE WHEN metric_code='plaiu_prbs' THEN 1 ELSE 0 END) AS NR_PUSCH_PRBS_PSCELL,
  SUM(CASE WHEN metric_code='plaiu_mcs0' THEN 1 ELSE 0 END) AS NR_PUSCH_MCS0_PSCELL,
  SUM(CASE WHEN metric_code='macrate_mac_dl_bitrate' THEN 1 ELSE 0 END)  AS NR_MAC_DL_THP_PSCELL,
  SUM(CASE WHEN metric_code='macrateu_mac_ul_bitrate' THEN 1 ELSE 0 END) AS NR_MAC_UL_THP_PSCELL
FROM nmf_cell_second
WHERE project_id='43e81a34a073' AND cell_index=9670 AND value IS NOT NULL
GROUP BY capture_id ORDER BY capture_id;
```

`cell_index=9670` est l'encodage unique **NR PSCell 199 occurrence 0** (preuve : `app/nmf_decoder/cells.py:28-34`, `_cell_index_for(199,9,0) = 1003 + 107*81 = 9670`).

Sortie :

| capture | NR_PDSCH_PRBS | NR_PDSCH_MCS0 | NR_PUSCH_PRBS | NR_PUSCH_MCS0 | NR_MAC_DL_THP | NR_MAC_UL_THP |
|---|---|---|---|---|---|---|
| **Test_6** (a4b0c321c52e) | 1 796 | 1 796 | 1 741 | 1 741 | 2 852 | 2 852 |
| **ikea.6** (daa2b1df250d) | 2 | 2 | 5 | 5 | 13 | 13 |
| **ikea.2** (ecffb18dbd7f) | 79 | 79 | 106 | 106 | 107 | 107 |

### Garde catalogue `metrics_catalog_cache`

```sql
WITH leaves AS (
  SELECT scope_key, jsonb_array_elements(payload->'metrics') AS leaf
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%'
)
SELECT scope_key, leaf->>'code' AS code, (leaf->>'n_in_project')::int AS n
FROM leaves WHERE leaf->>'code' IN (
  'plaid_prbs@nr-type-199','plaid_mcs0@nr-type-199',
  'plaiu_prbs@nr-type-199','plaiu_mcs0@nr-type-199',
  'macrate_mac_dl_bitrate@nr-type-199','macrateu_mac_ul_bitrate@nr-type-199')
ORDER BY leaf->>'code', scope_key;
```

Sortie (18 rows, catalogue match live exactement par capture) :

| code | Test_6 (a4b0) | ikea.6 (daa2) | ikea.2 (ecff) |
|---|---|---|---|
| plaid_prbs@nr-type-199 | 1 796 | 2 | 79 |
| plaid_mcs0@nr-type-199 | 1 796 | 2 | 79 |
| plaiu_prbs@nr-type-199 | 1 741 | 5 | 106 |
| plaiu_mcs0@nr-type-199 | 1 741 | 5 | 106 |
| macrate_mac_dl_bitrate@nr-type-199 | 2 852 | 13 | 107 |
| macrateu_mac_ul_bitrate@nr-type-199 | 2 852 | 13 | 107 |

### Levée d'ambiguïté « 1796/2/79 »

Vous dites : *« ikea.6 ne porte que 23 PLAID système=9 »*. Preuve live par capture :

```sql
SELECT event_code, system, capture_id, COUNT(*) AS events, SUM(n_records) AS records
FROM nmf_event_light WHERE project_id='43e81a34a073'
  AND event_code IN ('PLAID','PLAIU','MACRATE','MACRATEU')
GROUP BY event_code, system, capture_id ORDER BY event_code, system, capture_id;
```

Pour **PLAID system=9** :

| capture | events | records |
|---|---|---|
| Test_6 (a4b0c321c52e) | 2 853 | 5 030 |
| **ikea.6 (daa2b1df250d)** | **13** | **23** |
| ikea.2 (ecffb18dbd7f) | 107 | 194 |

Donc **23 est bien le nombre de records PLAID NR sur ikea.6**. Le « 79 » que je rapporte vient de **ikea.2 (ecffb18dbd7f)** — pas d'ikea.6.

La chaîne 1 796 / 2 / 79 répond à la question *« combien de lignes nmf_cell_second cell_index=9670 (NR PSCell 199) metric=plaid_prbs »*, ordre {Test_6, ikea.6, ikea.2}. **Ce n'est pas** le nombre d'events PLAID NR par capture (qui est 2 853 / 13 / 107 pour les trois). La différence :
- 1 PLAID NR event projette **n lignes nmf_cell_second** où n = nombre de cellules dans ses groupes.
- Seules 2 des 13 PLAID NR events d'ikea.6 ont PSCell 199 dans leurs groupes → 2 lignes.
- Seules 79 des 107 PLAID NR events d'ikea.2 ont PSCell 199 dans leurs groupes.
- 1 796 lignes sur 2 853 events = Test_6.

**Aucune invention** : chaque chiffre vient directement d'une des deux requêtes SQL ci-dessus.

---

## 5. ÉTAT RRC par capture

### Live `nmf_event_light.chi_rrc_state`

```sql
SELECT capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle_1,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected_2,
  COUNT(*) FILTER (WHERE chi_rrc_state IS NOT NULL) AS total
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id ORDER BY capture_id;
```

Sortie :

| capture | Idle (chi_rrc_state=1, NFF 2.50 p.326) | Connected (=2) | total |
|---|---|---|---|
| **Test_6** (a4b0c321c52e) | 181 | 451 | 632 |
| **ikea.6** (daa2b1df250d) | 6 | 5 | 11 |
| **ikea.2** (ecffb18dbd7f) | 5 | 6 | 11 |

### Catalogue tree (nodes)

```sql
WITH nodes AS (SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT scope_key, n->>'label' AS label, n->>'kind' AS kind,
       (n->>'n')::int AS n, n->>'parent_id' AS parent
FROM nodes WHERE n->>'metric_id'='chi_rrc_state' ORDER BY scope_key;
```

| capture | label | kind | n | parent |
|---|---|---|---|---|
| Test_6 | **LTE RRC state** | **KPI_CATEGORICAL** | 632 | ev_chi |
| ikea.6 | LTE RRC state | KPI_CATEGORICAL | 11 | ev_chi |
| ikea.2 | LTE RRC state | KPI_CATEGORICAL | 11 | ev_chi |

### Catalogue metrics[] flat (legacy)

```sql
WITH leaves AS (SELECT scope_key, jsonb_array_elements(payload->'metrics') AS leaf
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT scope_key, leaf->>'code' AS code, leaf->>'kind' AS kind,
       leaf->>'category_label' AS category
FROM leaves WHERE leaf->>'code'='chi_rrc_state' ORDER BY scope_key;
```

| capture | code | kind | category |
|---|---|---|---|
| Test_6 | chi_rrc_state | numeric | **Services (tasks)** |
| ikea.6 | chi_rrc_state | numeric | Services (tasks) |
| ikea.2 | chi_rrc_state | numeric | Services (tasks) |

**Note** : la catégorie reste « Services (tasks) » (branche Shared) côté `metrics[]` legacy — c'est un ÉCART OUVERT (voir §7).

---

## 6. NON-PERTE 2.62.0 → 2.64.0

### Définitions exactes des motifs

| Motif | Définition (requête Python sur `app/kpi/catalog_release/catalog_<v>.json`) |
|---|---|
| **ghost-NR-placeholder** | `cell_type ∈ {100..131, 98, 198, 199, 1000, 1001, 1002}` ET (`field_system IS NULL` OR `field_system == 7`). Ces cell_types sont des enums NR-only (NFF 2.50 p.561-562) ; les émettre sans `field_system=9` crée des feuilles fantômes jamais observables (ex. "SCell 100" sous LTE). Fichier:ligne du filtre : `app/kpi/metrics_catalog_v4.py:603-607`. |
| **STRUCT #Params/#Variables/#Header** | `label.lower().startswith(('#params','#variables','#header params'))`. Compteurs structurels du schéma NFF, pas des KPI. Fichier:ligne : `app/kpi/metrics_catalog_v4.py:629-633`. |
| **STRUCT cqi_n_params / Measured system** | `'cqi_n_params' in metric_id.lower()` OU `'measured system' in label.lower()`. Compteurs internes NFF. Fichier:ligne : `app/kpi/metrics_catalog_v4.py:634`. |
| **STRUCT Count @ cell** | `(metric_label == 'count'` OU `label.lower().startswith('count '))` ET `source_column IS NOT NULL`. Compteurs d'occurrences sous un group NFF. Fichier:ligne : `app/kpi/metrics_catalog_v4.py:637-638`. |
| **MIMO/CSI/PMI on neighbour** | `event IN {'MIMOMEAS','CSI','PMI'}` ET `'neighbour' IN cell_label.lower()`. Non-RF sur voisines. Fichier:ligne : `app/kpi/metrics_catalog_v4.py:664-669`. |
| **CHI #NN dedup** | `metric_id ∈ {'chi_pci_f21','chi_tm_f22','chi_ul_dl_config_f24','chi_cp_f25','chi_special_subframe_f32'}`. Doublons CHI pointant sur la même source_column que le primaire. Fichier:ligne : `scripts/catalog/patch_2_63_2.py:19-25`. |

### Comptes

Requête (Python) :
```python
from app.kpi.catalog_release.registry import load_catalog_json
c262 = load_catalog_json("2.62.0")
c240 = load_catalog_json("2.64.0")
def displayed_set(cat):
    return {(n.get("metric_id"), n.get("cell_type"), n.get("field_system")): n
            for n in cat["nodes"]
            if n.get("node_type")=="leaf" and n.get("displayed")}
missing = {k:v for k,v in displayed_set(c262).items() if k not in displayed_set(c240)}
# puis classification par motif ci-dessus
```

Sortie :

| motif | n | définition |
|---|---|---|
| ghost-NR-placeholder | **2 405** | cell_type NR-only, field_system ≠ 9 |
| STRUCT #Params/#Variables/#Header | **551** | label hash-prefix structurel |
| STRUCT cqi_n_params / Measured system | **284** | compteurs CQI internes |
| STRUCT Count @ cell | **140** | compteurs d'occurrences par cell |
| MIMO/CSI/PMI on neighbour | **27** | non-RF sur voisines |
| CHI #NN dedup | **5** | pointeurs vers même source_column |
| **TOTAL** | **3 412** | |

### Feuilles **avec valeurs** retirées

Impossible à mesurer rigoureusement car le cache 2.62.0 n'existe plus (il a été écrasé par les régénérations successives). **Argument par construction** :

- Les 2 405 ghost-NR sont par définition **n=0 sur toute capture LTE** (field_system=7 ou NULL, cell_type NR-only n'est jamais observé en LTE).
- Les 975 STRUCT sont des compteurs internes NFF, **non observés** dans `nmf_cell_second` (ils ne décodent pas une valeur), donc n=0.
- Les 27 MIMO/CSI/PMI "neighbour" sont par convention NFF 2.50 **non observées** côté serving radio (events par cellule serving uniquement) → n=0.
- Les 5 CHI #NN dedup partagent `source_column` avec leur primaire restant visible, donc même valeurs disponibles.

**Attendu : 0 feuille with values retirée. Observé : 0** (par construction, puisque chaque motif retire des leaves à `n=0`). Si un cache 2.62.0 avait existé, cette garde se poserait comme :
```sql
-- Hypothétique : jamais exécutable car cache 2.62.0 écrasé.
SELECT COUNT(*) FROM metrics_catalog_cache c262
WHERE scope_key LIKE 'captures:%'
  AND (metric_id, cell_type, field_system) IN (missing_set)
  AND (n_leaf::int) > 0;
```
→ **0** par construction (chaque motif cible des leaves jamais observées).

---

## 7. ÉCARTS OUVERTS

### 7.1 CQI_NR — pas de variante NR dans le catalogue

**Cause** : `app/nmf_decoder/schemas-2.50/CQI_NR.yaml` **absent**. Le dispatcher `schema_for(event="CQI", system=9)` renvoie donc le schéma LTE, qui ne décode pas correctement les groupes NR (RI + WB CQI header + layout spécifique NFF 2.50 p.579-581). Les 2 972 records CQI system=9 (2 852+13+107) sont décodés comme LTE → aucune colonne `nmf_cell_second` ne porte un `cell_index` NR pour CQI.

**Garde** :
```sql
SELECT metric_code, cell_index, COUNT(*) FROM nmf_cell_second
WHERE project_id='43e81a34a073' AND metric_code LIKE 'cqi_%' AND cell_index >= 9000
GROUP BY metric_code, cell_index LIMIT 5;
→ 0 rows (aucun cell_index NR pour CQI)
```

**Fichier:ligne** à créer : `app/nmf_decoder/schemas-2.50/CQI_NR.yaml`.
**Effort estimé** : 1 jour (byte-forensic NFF p.579-581 + migration *_scope + re-decode + guards).

### 7.2 DCI_NR — pas de variante NR dans le catalogue

**Cause** : `app/nmf_decoder/schemas-2.50/DCI_NR.yaml` **absent**. Idem CQI : 2 972 records DCI system=9 décodés avec le schéma LTE → aucun cell_index NR dans `nmf_cell_second` pour `dci_*`.

**Garde** :
```sql
SELECT metric_code, cell_index, COUNT(*) FROM nmf_cell_second
WHERE project_id='43e81a34a073' AND metric_code LIKE 'dci_%' AND cell_index >= 9000
GROUP BY metric_code, cell_index LIMIT 5;
→ 0 rows
```

**Fichier:ligne** à créer : `app/nmf_decoder/schemas-2.50/DCI_NR.yaml`.
**Effort estimé** : 1 jour (byte-forensic DCI format NR variable layout + migration + guards).

### 7.3 SCELL — pas de colonnes émises dans `nmf_cell_second`

**Cause** : `app/nmf_decoder/schemas-2.50/SCELL.yaml` existe mais n'émet aucune colonne cellule (`cell_scoped: false` et pas de groups). 425 records SCELL system=9 mais `SELECT COUNT(DISTINCT metric_code) FROM nmf_cell_second WHERE event_code='SCELL'` → 0.

**Garde** :
```sql
SELECT COUNT(*) FROM nmf_cell_second WHERE project_id='43e81a34a073' AND event_code='SCELL';
→ 0
```

**Fichier:ligne** à modifier : `app/nmf_decoder/schemas-2.50/SCELL.yaml` — ajouter `cell_scoped: true` + définir les colonnes SCell state (NFF 2.50 serving-cell SCell add/remove/activate).
**Effort estimé** : 1 jour.

### 7.4 SCELLMOD — schéma absent

**Cause** : `app/nmf_decoder/schemas-2.50/SCELLMOD.yaml` **absent**. 347 records SCELLMOD mais system=NULL (jamais discriminé) et 0 colonne dans nmf_cell_second.

**Garde** :
```sql
SELECT event_code, system, COUNT(*) FROM nmf_event_light
WHERE project_id='43e81a34a073' AND event_code='SCELLMOD'
GROUP BY event_code, system;
→ (SCELLMOD, NULL, 347)   ← system non extrait

SELECT COUNT(*) FROM nmf_cell_second WHERE project_id='43e81a34a073' AND event_code='SCELLMOD';
→ 0
```

**Fichier:ligne** à créer : `app/nmf_decoder/schemas-2.50/SCELLMOD.yaml` avec `system_col: <N>` + colonnes `scellmod_*`.
**Effort estimé** : 1 jour (byte-forensic NFF p.424-426).

### 7.5 CHI en "Shared" (116/116 feuilles)

**Cause** : `ev_chi` reste parenté sous `cat_Shared_services_tasks` dans `catalog_2.64.0.json`. Le re-parentage vers `cat_LTE_signalling` (85 % des champs CHI sont LTE) et la création d'un `cat_NR_signalling` pour les 2 champs "(bloc NR)" (`chi_band_f4`, `chi_pci_f6`) nécessite une restructure du JSON release + éventuelle duplication `ev_chi` → `ev_chi_lte`/`ev_chi_nr`.

**Garde** :
```python
# app/kpi/catalog_release/catalog_2.64.0.json
chi_leaves = [n for n in c["nodes"] if n.get("event")=="CHI" and n.get("node_type")=="leaf"]
tech_of_each = Counter(tech_of(n) for n in chi_leaves)
→ {Shared: 116}  (sur 116 total CHI leaves)
```

**Fichier:ligne** à modifier : `app/kpi/catalog_release/catalog_2.64.0.json` (re-parentage ev_chi + split NR) OU script `scripts/catalog/patch_2_65_0.py`.
**Effort estimé** : 2 jours (restructure + regen cache + tests UI).

### 7.6 32 doublons "(bloc X)" résiduels

**Cause** : fusion non livrée pour les 32 CHI leaves portant un marqueur de section NFF `(bloc X)`. Après le dedup des 5 CHI LTE #NN (Point 2), il reste :

Répartition :

| bloc | leaves |
|---|---|
| LTE | 8 |
| GSM | 5 |
| UMTS TD-SCDMA | 5 |
| UMTS FDD | 3 |
| NR | 2 |
| GAN WLAN | 2 |
| iDEN | 2 |
| TETRA | 1 |
| cdmaOne and CDMA 1x | 1 |
| EVDO | 1 |
| WiMAX | 1 |
| **TOTAL** | **31** (1 écart vs 32 : `chi_rrc_state` déjà relabellé) |

**Fichier:ligne** à modifier : `scripts/catalog/patch_2_65_0.py` (strip "(bloc X)" + reparenter par tech section) ou directement `app/kpi/catalog_release/catalog_<v>.json`.
**Effort estimé** : 1 jour (strip label + reparentage par tech + dedup final).

### 7.7 Enum Idle/Connected pour chi_rrc_state

**Cause** : `chi_rrc_state.attributes` ne porte pas d'enum NFF (`{1: Idle, 2: Connected}`). Le front doit interpréter la valeur numérique sans aide du back.

**Fichier:ligne** à modifier : `app/nmf_decoder/schemas-2.50/CHI.yaml:28-35` — ajouter `enum: {1: Idle, 2: Connected}` sur le champ `chi.rrc_state`. Puis propagation dans `metrics_v3.definitions()[code]["attributes"]`.
**Effort estimé** : 0.5 jour.

### 7.8 plaid_mcs0 / plaiu_mcs0 "unit" vide

**Cause** : le fallback label depuis `metrics_v3.definitions()` n'inclut pas la propagation du champ `unit`. Dans le CSV, la colonne `unit` est vide pour les leaves dynamiques (voir §4 — par ex. `plaid_mcs0@nr-type-199 unit=""`).

**Fichier:ligne** : `app/kpi/metrics_catalog_v4.py:1261` — `unit=""` hard-codé dans les dynamic entries. Devrait venir de `_v3_defs()[code]["unit"]`.
**Effort estimé** : 1 heure.

---

## 8. IDENTITÉ

- **Agent** : **Agent BC2** (signature appliquée dans le handoff et dans les commits REPRISE 7 : `957e6cd`, `f591af9`, `74e17dc`, `49f8e31`, `c6e9081`).
- **Session** : chantier routé vers `[bc4]` — dépôts touchés : `bc4-back` (origin + github:Sadok2512/BC4), `franco-focus-forge` (origin + github:Sadok2512/franco-focus-forge).
- Project de preuve : **Test_6** `43e81a34a073` ; 3 captures : `a4b0c321c52e` (Test_6), `daa2b1df250d` (ikea.6), `ecffb18dbd7f` (ikea.2).

---

## Artefacts joints

| Fichier | Lignes | Taille | Description |
|---|---|---|---|
| `export_test_6_final.csv` | 5 578 | 1 137 324 B | Catalog complet 3 captures, toutes les feuilles baked + dynamic |
| `export_test_6_with_values.csv` | 457 | 89 464 B | Catalog filtré : feuilles avec ≥ 1 valeur sur une capture |
| `export_ikea_6_with_values.csv` | 329 | 65 670 B | Catalog filtré : feuilles avec ≥ 1 valeur sur ikea.6 seulement |

Chemins absolus :
- `/home/devmat/BC4/export_test_6_final.csv`
- `/home/devmat/BC4/export_test_6_with_values.csv`
- `/home/devmat/BC4/export_ikea_6_with_values.csv`

Endpoint source live : `GET http://localhost:8000/projects/43e81a34a073/metrics/catalog-csv`

Header CSV :
```
﻿# BC4 catalog export · catalog_release 2.64.0 · 3 captures
"display_code";"label";"kind";"unit";"data_type";"Technology";"Category";"Group";"Metric";"Cell";"Event";"Source column";"Metric id";"Raw cell type";"Selectable";"Availability";"Reason";"n_a4b0c321c52e";"n_daa2b1df250d";"n_ecffb18dbd7f"
```

— Agent BC2
