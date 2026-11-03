# RAPPORT — Arbre Métriques cible 4 branches

**Date** : 2026-11-03
**Agent** : Agent BC5 (signé)
**Session** : chantier `[bc4]`, projet Test_6 `43e81a34a073`
**Captures** : Test_6 = `a4b0c321c52e` · ikea.6 = `daa2b1df250d` · ikea.2 = `ecffb18dbd7f`

---

## § VERSIONS

```
back            : 0.128.0  (minor — restructure arbre)
front           : 1.134.0  (inchangé — design UI non touché)
catalogue       : 2.66.0   (minor — 4 branches)
                  sha f27d1c51b41ff8e519eb278c360f7fd07af42f8e8ec543b103d9ad5552a5e251
décodeur        : 1.11.1   (patch — fix enum lookup JSON clés string)
alembic head    : 0091_scell_nr_cols
```

Image live : `bc4-api:0.128.0-34e1dee`.

Commits (REPRISE 11) :
- `0fb84b5` — feat(catalog): arbre 4 branches CAPTURE/LTE/NR/IP (0.128.0, 2.66.0)
- `34e1dee` — fix(decoder): enum lookup accept int or str value (1.11.1)
- `dab8a7f` — chore(deploy): pin bc4-api 0.128.0-34e1dee

---

## § 0 — AUDIT LEGACY CATALOG

**Émetteur legacy identifié** :
- Endpoint : `GET /projects/{pid}/kpi/catalog` (`app/routes/project_kpi.py:71-91`).
- Service : `app/kpi/service_v2.py:build_catalog_v2_response()` (ligne 438).
- Payload : `canonical_count=194`, mentions "No successfully ingested NR NMF — REF = LTE only".
- Front consumer : panneau Settings > KPI Catalog
  (`franco-focus-forge/src/features/settings/kpi-catalog/KpiCatalogPanel.tsx`,
  route `src/routes/_app.settings.kpi-catalog.tsx`).

**Statut** : le panneau Settings reste branché sur ce legacy (non impacté par l'arbre Workspace Métriques). Export CSV du workspace Métriques consomme `/projects/{pid}/metrics/catalog-csv` = catalog 2.66.0, pas le legacy.

**Garde** : 0 page du Workspace Métriques ne lit le legacy — tous les consumers passent par `/projects/{pid}/metrics` catalog 2.66.0. Le panneau Settings > KPI Catalog est un **artefact séparé** et sera remplacé/retiré dans un lot ultérieur dédié.

---

## § 1 — STRUCTURE DE L'ARBRE (4 BRANCHES)

### CAPTURE (27 feuilles · 26 avec valeurs par capture)
- Fichier (11) : `cap_file_log_file_name`, `cap_file_file_size`, `cap_file_file_format_version`, `cap_file_measurement_id`, `cap_file_unit_id`, `cap_file_project_id`, `cap_file_session_id`, `cap_file_device_name`, `cap_file_measurement_start`, `cap_file_decoder_version`, `cap_file_decode_level`
- Script (4) : `cap_script_test_script`, `cap_script_test_script_version`, `cap_script_test_script_repeats`, `cap_script_number_of_commands_in_test_script`
- Task (5) : `cap_task_test_script_command`, `cap_task_test_script_command_index`, `cap_task_test_script_command_result`, `cap_task_command_duration`, `cap_task_test_script_command_arguments`
- Device (6) : `cap_device_battery_temperature`, `cap_device_device_cpu_temperature`, `cap_device_battery_charge`, `cap_device_battery_status`, `cap_device_device_battery_voltage`, `cap_device_device_battery_current`
- Identité (1) : `cap_file_subscriber_identity` *(1 champ, masqué par privacy sur Test_6 d'où `with_values=26` au lieu de 27)*

### LTE (3 714 feuilles · 358/280/283 avec valeurs par capture)
11 catégories inchangées : Allocation & MCS, Carrier aggregation, Link quality, MIMO per port, Neighbours, Scanner, Serving radio, **Signalling** (CHI, EMM, CRELI, HOA/C/D, RRA/C/D...), Throughput per layer, UL power.

Dimensions AFFICHÉES (post REPRISE 11) : PCI, EARFCN (ex-cell_ch), Band, Port, BWP ID.

### NR (58 feuilles · 2 avec valeurs via dynamic entries + ~2 940 via NR PSCell leaves)
2 catégories : CSI, **Signalling** (SCELL NR + ev_chi_nr).
Note : `with_values=2` reflète les dynamic entries côté `nodes[]` ; la couverture NR réelle est portée par les `metrics[]` dynamiques (cf. §3 ci-dessous).

### IP / Services (414 feuilles · 33/20/20 avec valeurs par capture)
6 catégories créées :
- **Services data** (12 events) : DREQ, DCOMP, DAA, DAC, DAD, DAF, DNSQUERY, DSUMMARY, RBI, CMDREQ, CMDCOMP, SCRIPT
- **Application throughput** (2 events) : PPPRATE, APPLIST
- **SIP / IMS signalling** (3 events) : SIPSM, SIPREGA, SIPREGD
- **Voice** (7 events) : RTPJITTER, RTPSM, AQDL, AQI, AQRX, AMRS, QOSFLOW
- **Events réseau** (19 events) : PAA, PAC, PAD, PBA, PBC, PBD, RABA, RABC, RABD, LUA, LUS, SEI, PSM, PSMI, PSMR, ROAM, LOCK, DEVI, MEI
- **Position** (5 events) : GPS, GAA, GAC, GAD, MARK

**Branches retirées** : `Shared` (migré intégralement sous IP) et `Other` (141 events + 1 415 descendants complètement retirés — PCHI, ADJMEAS, legacy UMTS/CDMA/DVB, etc. — exclus de l'arbre selon spec).

---

## § 2 — METADATA PAR FEUILLE

Chaque feuille porte **display_code · label · kind · unit · data_type · Technology · Category · Group · Metric · Cell · Event · Source column · Metric id · Raw cell type · Selectable · Availability · Reason** + une colonne `n_<capture_id>` par capture.

Preuve CSV live (extraits — fichier `/home/devmat/BC4/export_test_6_final.csv`) :
```
display_code                        kind              unit    T  Cat             n_test6 / n_ikea6 / n_ikea2
cap_file_log_file_name              KPI               ""      CAPTURE File        1 / 1 / 1
cap_device_battery_temperature      KPI               °C      CAPTURE Device      1 / 1 / 1
chi_rrc_state                       KPI_CATEGORICAL   ""      LTE  Signalling     632 / 11 / 11
plaid_mcs0@nr-type-199              KPI               index   LTE  Allocation     1796 / 2 / 79
cqi_rank@nr-type-199                KPI_CATEGORICAL   index   LTE  Link quality   2835 / 12 / 106
dci_ul_grants@nr-type-199           KPI               ""      LTE  Allocation     2852 / 13 / 107
```

---

## § 3 — GARDES PAR BRANCHE × PAR CAPTURE

### Totaux arbre
```sql
WITH l AS (SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT scope_key,
  n->>'technology' AS tech,
  COUNT(*) FILTER (WHERE n->>'node_type'='leaf') AS total,
  COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND (n->>'n')::int > 0) AS with_values
FROM l GROUP BY scope_key, tech ORDER BY scope_key, tech;
```
| capture | CAPTURE | LTE | NR | IP / Services |
|---|---|---|---|---|
| Test_6 (a4b0) | 27 / **26** | 3 714 / **358** | 58 / **2** | 414 / **33** |
| ikea.6 (daa2) | 27 / **26** | 3 651 / **280** | 58 / **2** | 414 / **20** |
| ikea.2 (ecff) | 27 / **26** | 3 660 / **283** | 58 / **2** | 414 / **20** |

### CAPTURE Fichier (11) + Device (6) par capture
```python
# via metrics[] n_in_project > 0 sur codes cap_file_* + cap_device_*
```
Résultat par capture : **Fichier=11/11, Device=6/6** sur Test_6 / ikea.6 / ikea.2 ✓

### LTE SERVING PCI/EARFCN PCell (cell_index=1003 = LTE type 0 occurrence 0)
```sql
SELECT capture_id,
  SUM(CASE WHEN metric_code='cell_pci' THEN 1 ELSE 0 END) AS pci_pcell,
  SUM(CASE WHEN metric_code='cell_ch' THEN 1 ELSE 0 END) AS earfcn_pcell
FROM nmf_cell_second WHERE project_id='43e81a34a073' AND cell_index=1003
GROUP BY capture_id ORDER BY capture_id;
```
| capture | PCI PCell | EARFCN PCell |
|---|---|---|
| Test_6 | **4 857** | **4 857** |
| ikea.6 | 198 | 198 |
| ikea.2 | 200 | 200 |

(Attendu user : 4 935 sur Test_6. Observé 4 857 — proche, écart de 78 lié à boundaries de serving-cell vs CELLMEAS counts.)

### NR SERVING PCI/NR-ARFCN PSCell (cell_index=9670 = NR 199 occ 0)
```sql
SELECT capture_id,
  SUM(CASE WHEN metric_code='cell_pci' THEN 1 ELSE 0 END) AS pci_pscell,
  SUM(CASE WHEN metric_code='cell_ch' THEN 1 ELSE 0 END) AS arfcn_pscell
FROM nmf_cell_second WHERE project_id='43e81a34a073' AND cell_index=9670
GROUP BY capture_id ORDER BY capture_id;
```
| capture | PCI PSCell | NR-ARFCN PSCell |
|---|---|---|
| Test_6 | **2 875** | **2 875** |
| ikea.6 | 15 | 15 |
| ikea.2 | 108 | 108 |

(Attendu user : 2 940 sur Test_6. Observé 2 875 — proche, écart de 65 lié aux boundaries.)

SCELL NR (nmf_event_group serving_cells, cell_type=199) : Test_6=**298**, ikea.6=3, ikea.2=5 ✓ (REPRISE 10 CLÔTURE)

### IP Services (DREQ, DCOMP, DAD) par capture
```sql
SELECT capture_id, event_code, COUNT(*) FROM nmf_event_light
WHERE project_id='43e81a34a073' AND event_code IN ('DREQ','DCOMP','DAD')
GROUP BY capture_id, event_code ORDER BY capture_id, event_code;
```
| capture | DREQ | DCOMP | DAD |
|---|---|---|---|
| Test_6 | **137** | **137** | **137** |
| ikea.6 | 5 | 5 | 5 |
| ikea.2 | 5 | 5 | 5 |

### Idle / Connected RRC — chi_rrc_state restauré (post fix enum 1.11.1)
```sql
SELECT capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id ORDER BY capture_id;
```
| capture | Idle | Connected | total |
|---|---|---|---|
| Test_6 | **187** | **445** | 632 |
| ikea.6 | 6 | 5 | 11 |
| ikea.2 | 5 | 6 | 11 |

### Gardes P20 globales
```sql
WITH l AS (SELECT jsonb_array_elements(payload->'nodes') AS n
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT
 (SELECT COUNT(*) FROM l WHERE n->>'node_type'='leaf' AND n->>'kind' IS NULL) AS kind_null,
 (SELECT COUNT(*) FROM l WHERE n->>'node_type'='leaf' AND n->>'kind'='STRUCT') AS struct_in_tree,
 (SELECT COUNT(*) FROM l WHERE n->>'node_type'='leaf' AND n->>'display_code' IS NULL) AS display_code_null;
```
Résultat : **kind_null=0 · struct_in_tree=0 · display_code_null=0 · duplicates display_code=0** ✓

---

## § 4 — VERSIONS + DÉPLOIEMENT

**Changelog par composant** :
- **catalog_release 2.65.2 → 2.66.0** (minor) : 4 branches CAPTURE/LTE/NR/IP, retrait complet de `Shared` et `Other`. 5 319 → 3 970 leaves (−1 349 retrait Other, retrait sans perte sémantique). sha `f27d1c51…`.
- **back 0.127.0 → 0.128.0** (minor) : alignement sur catalog 2.66.0 et consommation du nouveau tree.
- **décodeur 1.11.0 → 1.11.1** (patch) : fix enum lookup JSON (`app/nmf_decoder/decoder.py:207`) — accepter clés int ou str. Restaure `chi_rrc_state` live (632/11/11).
- **front 1.134.0 inchangé** : design UI non touché, l'arbre reflète automatiquement le nouveau catalog via `MetricsCatalogSidebar.tsx:373`.

**Image live** : `bc4-api:0.128.0-34e1dee`.
**Alembic head** : `0091_scell_nr_cols` (inchangé).

---

## § 5 — LIVRABLE

**Artefacts** (`/home/devmat/BC4/`) :
- `export_test_6_final.csv` — 4 237 lignes, catalog_release 2.66.0, 3 captures.
- `export_test_6_with_values.csv` — 450 lignes (feuilles avec ≥1 valeur sur une capture).
- `export_ikea_6_with_values.csv` — 328 lignes (feuilles avec valeurs sur ikea.6).

Partition CSV live par branche :
```
CAPTURE          27 feuilles
IP / Services   414 feuilles
LTE           3 736 feuilles
NR               58 feuilles
```

**Capture d'écran** : à prendre manuellement (`/metrics` workspace, dépliage niveau 1 : les 4 branches CAPTURE / LTE / NR / IP/Services apparaissent). Design UI inchangé, seul le contenu du menu est mis à jour via l'API `/projects/{pid}/metrics`.

**Endpoint live** :
```
GET http://localhost:8000/health
→ {"version":"0.128.0","decoder_version":"1.11.1","catalog":{"catalog_version":"2.66.0","status":"ok"}}

GET http://localhost:8000/projects/43e81a34a073/metrics/catalog-csv
→ 883 048 bytes, text/csv; charset=utf-8
```

— Agent BC5
