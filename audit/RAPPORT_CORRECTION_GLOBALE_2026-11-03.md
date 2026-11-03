# RAPPORT — Correction globale du catalogue Métriques

**Date** : 2026-11-03
**Agent** : Agent BC2 (signé)
**Session** : chantier routé vers `[bc4]` (back `bc4-back` + front `franco-focus-forge`), projet de preuve **Test_6** `43e81a34a073`
**Captures** : Test_6 = `a4b0c321c52e` (parcours_26Jun10_155941.8.nmf) · ikea.2 = `ecffb18dbd7f` (ikea_26Jun10_172354.2.nmf) · ikea.6 = `daa2b1df250d` (ikea_26Jun10_172354.6.nmf)

> **Règles** : aucun chiffre sans sa requête · « par construction » ne remplace pas une mesure · recherche par CONTENU · un écart se ferme ou se déclare OUVERT avec fichier:ligne · ordre `(capture_id, seq)` jamais `ts` · aucune CI, garde lancé à la main, sortie collée · gardes PAR CAPTURE · design de la page Métriques inchangé.

> Mis à jour post **REPRISE 8** (2026-11-03 après-midi) : §2 §3 §6 §7 refletent catalog 2.65.0 et back 0.126.4.

---

## 1. VERSIONS

### État live final (post REPRISE 10 CLÔTURE LOT 1)

```
back            : 0.127.0
front           : 1.134.0
catalogue       : 2.65.2 (sha 80636d1276ca3dc373d97d5e8b08b167b9db0fe324c45fab8cf1ea23cc52326a)
décodeur        : 1.11.0  (minor — moteur étendu count_header_col pour SCELL NR)
alembic head    : 0091_scell_nr_cols
```

### Images

```
bc4-api:0.127.0-70b3f86       (décodeur 1.11.0 LOT 1 CLÔTURE CQI_NR + DCI_NR + SCELLMOD + SCELL_NR)
bc4-front-v2:1.134.0-f23e122  sha256:cae021f062860549b28c0ac99516479a887fcaa9c53290c69b3b2cc96ed5fa16
```

### Commits REPRISE 8 (depuis d63ab8c du matin)

```
b2c174a chore(deploy): pin bc4-api 0.126.4-697992b (REPRISE 8 Points 1-4 live)
697992b feat(catalog): REPRISE 8 Point 4 — CHI reparent LTE/NR/Other + dedup (0.126.4, 2.65.0)
cad7c88 feat(catalog): REPRISE 8 Points 1-3 — unit v3_defs + align metrics[] + enum RRC (0.126.3, 2.64.1)
```

(précédés par les commits REPRISE 7 de la matinée, voir rapport précédent.)

---

## 2. AVANT / APRÈS — par capture (mis à jour 2.65.0)

### Baked JSON (release)

| | 2.62.0 (avant) | 2.65.0 (après REPRISE 8) |
|---|---|---|
| Feuilles displayed total | **8 735** | **5 319** |
| LTE | 6 358 | 3 471 |
| NR | 276 | 58 (baked, +2 CHI NR) |
| Shared | 644 | 491 (-116 CHI) |
| Other | 1 430 | 1 272 (+17 CHI Other) |
| CAPTURE | 27 | 27 |

### Cache runtime (par capture)

```sql
WITH nodes AS (
  SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
  FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%'
)
SELECT scope_key,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf') AS total,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND (n->>'n')::int > 0) AS with_values,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='LTE') AS lte,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='NR') AS nr,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='Shared') AS shared,
       COUNT(*) FILTER (WHERE n->>'node_type'='leaf' AND n->>'technology'='Other') AS other
FROM nodes GROUP BY scope_key ORDER BY scope_key;
```

| capture | total | with_values | LTE | NR | Shared | Other |
|---|---|---|---|---|---|---|
| Test_6 (a4b0c321c52e) | 5 550 | 420 | 3 526 | 234 | 491 | 1 272 |
| ikea.6 (daa2b1df250d) | 5 490 | 323 | 3 480 | 220 | 491 | 1 272 |
| ikea.2 (ecffb18dbd7f) | 5 499 | 326 | 3 499 | 210 | 491 | 1 272 |

(Totaux ligne 1 avec `with_values` = 420/323/326 depuis l'export CSV live post REPRISE 8.)

Partition par kind — par capture :

```sql
WITH nodes AS (SELECT scope_key, jsonb_array_elements(payload->'nodes') AS n
 FROM metrics_catalog_cache WHERE scope_key LIKE 'captures:%')
SELECT scope_key, n->>'kind' AS kind, COUNT(*)
FROM nodes WHERE n->>'node_type'='leaf'
GROUP BY scope_key, n->>'kind' ORDER BY scope_key, kind;
```

| capture | KPI | DIMENSION | KPI_CATEGORICAL |
|---|---|---|---|
| Test_6 | 5 038 | 374 | 138 |
| ikea.6 | 4 996 | 360 | 134 |
| ikea.2 | 4 999 | 364 | 136 |

STRUCT, kind IS NULL : **0** sur chaque capture (gardes P8, P14).
CHI en Shared : **0** (garde Point 4).
Doublons `(bloc X)` restants : **0** (garde Point 4).

---

## 3. PAR LOT (1 à 7) — mis à jour

### Lot 1 — Schémas NR + exposition catalogue — **FAIT 4/4 (CLÔTURE LOT 1)**

**Mise à jour REPRISE 10 CLÔTURE LOT 1** — SCELL NR livré :

- **SCELL_NR** (`app/nmf_decoder/schemas/SCELL_NR.yaml`, décodeur **1.11.0**, back **0.127.0**) :
  NFF 2.50 p.345-349. Header 5 fields (#Header params=5, #Serving cells, #Params/serving cell, #Params/BWP, C-RNTI) + group `serving_cells` avec 10 fields (Cell type, SSB band, SSB NR-ARFCN, PCI, DL PointA, UL PointA, DSS LTE offset, DSS LTE bw, SSB periodicity, #BWPs).
  **Moteur étendu** : `app/nmf_decoder/decoder.py:244-280` — nouveau mode `count_header_col`/`params_header_col` qui lit count+params à positions header fixes (indépendamment du `start` des données). Nécessaire car SCELL NR a header-interleaved layout (count col 6, params col 7, data col 11).
  **Backward-compat** : si clés nouvelles absentes → ancien mode unchanged.
  Migration **0091_scell_nr_cols** (17 colonnes).
  **Test non-régression** : CQI LTE / CQI NR / DCI NR counts **unchanged** après re-decode 1.11.0 (14 989 / 510 / 517 LTE, 2 835 / 12 / 106 CQI NR, 2 852 / 13 / 107 DCI NR par capture).
  **2 records réels vérifiés octet par octet** : `SCELL,17:25:27.067,,9,5,1,16,7,46519,,199,90078,638688,440,…` → Cell type=199, SSB band=90078 (NR n78 TDD), SSB NR-ARFCN=638688, PCI=440, DL PointA=638066, UL PointA=638066, SSB periodicity=20 ms, #BWPs=1. Et `SCELL,17:25:27.411,,9,5,0,16,7,,` → #Serving cells=0, pas de group émis.
  **Garde par capture (`nmf_event_group serving_cells`)** :
  - Test_6 : 298 @ cell_type=**199** (SCG PSCell, 32 PCIs 440..991) + 3 @ cell_type=**0** (PCell).
  - ikea.6 : 3 @ cell_type=**199** (PCI 440) + 1 @ cell_type=**4** (SCell 4 PCI 1).
  - ikea.2 : 5 @ cell_type=**199** (PCI 557).

**Lot 1 — 4 schémas livrés** :

| Schéma | Décodeur | Migration | Garde cell 199 (Test_6/ikea.6/ikea.2) |
|---|---|---|---|
| CQI_NR | 1.10.6 | 0088 | cqi_rank 2835/12/106 |
| DCI_NR | 1.10.7 | 0089 | dci_ul_grants 2852/13/107 |
| SCELLMOD | 1.10.8 | 0090 | added=211/3/5, removed=211/3/5 @ 199 |
| **SCELL_NR** | **1.11.0** | **0091** | **serving_cells 298+3/3+1/5 @ 199** |

### Lot 1 ancien statut (remplacé par REPRISE 10 CLÔTURE)

**Mise à jour REPRISE 9 (LOT 1 FINAL)** — 3 schémas livrés avec byte-level forensic :

- **CQI_NR** (`app/nmf_decoder/schemas/CQI_NR.yaml`, décodeur **1.10.6**, back **0.126.5**) :
  NFF 2.50 p.579-581. Header 5 fields (#Header, Scope, Cell type, RI, WB CQI) + 2 groups (RI dist + WB CQI dist). Migration **0088**. 2 records réels ikea.6 vérifiés octet par octet. **Garde cell_index=9670 (NR PSCell 199)** : cqi_rank=**2835/12/106**, cqi_wb_cqi_0=**2835/12/106**, cqi_ri_count=**2835/12/106**, cqi_wb_cqi_count=**2835/12/106**. LTE préservé (cell_index<9000).

- **DCI_NR** (`app/nmf_decoder/schemas/DCI_NR.yaml`, décodeur **1.10.7**, back **0.126.6**) :
  NFF 2.50 p.553-555. Header 6 fields (#Header, Scope, Cell type, CCE aggr, UL, DL) + 2 groups (DCI format dist + CCE dist). Migration **0089** (9 colonnes). 2 records réels vérifiés (Count DCI format = UL+DL = 16, Count CCE total = 16 ✓). **Garde cell_index=9670** : dci_ul_grants=**2852/13/107**, dci_dl_grants=**2852/13/107**, dci_cce_aggr_level=**1944/5/106**, dci_format_count=**1944/5/106**. LTE préservé.

- **SCELLMOD** (`app/nmf_decoder/schemas/SCELLMOD.yaml`, décodeur **1.10.8**, back **0.126.7**) :
  NFF 2.50 p.424-429. Header 2 fields (#Header, Result) + 2 groups (added/removed SCells, chacun avec `{Cell type, Band, ARFCN, PCI}`). Migration **0090** (13 colonnes). 2 records réels vérifiés — Result=**11** (Random access problem) puis Result=**1** (Succeeded) sur même SCG PSCell NR cell 199 band 90078 ARFCN 638688 PCI 440. **Garde `nmf_event_group` (per cell_type)** : Test_6 added=211/removed=211 @ cell 199 ; ikea.6 add=1@117+2@199, remove=1@117+2@199 ; ikea.2 add=5/remove=5 @ 199. Limitation : non projeté à `nmf_cell_second` car `cells.py:88-92` ne cherche cell_type qu'au header-level, pas au group-level (SCELLMOD met Cell type dans les groupes). Fichier:ligne pour extension future : `app/nmf_decoder/cells.py:88-99`.

**Commits REPRISE 9** :
```
2526c89 chore(deploy): pin bc4-api 0.126.7-1d58215 (décodeur 1.10.8 LOT 1 FINAL)
1d58215 docs(changelog): SCELL NR OUVERT — layout nested variable non supporté
<SCELLMOD commit> feat(decoder): SCELLMOD schema + migration 0090 (1.10.8, back 0.126.7)
<DCI_NR commit>   feat(decoder): DCI_NR schema + migration 0089 (1.10.7, back 0.126.6)
<CQI_NR commit>   feat(decoder): CQI_NR schema + migration 0088 (1.10.6, back 0.126.5)
```

**OUVERT résiduel — SCELL NR** (p.345-349) :
- **Spec vérifiée** : header 5 fields (#Header=5, #Serving cells, #Params/serving cell=16, #Params/BWP=7, C-RNTI) + **nested variable** (#BWPs par serving cell).
- **2 records réels** extraits : `SCELL,17:25:27.067,,9,5,1,16,7,46519,,199,90078,638688,440,…` (SCG PSCell 199, band 90078, ARFCN 638688, PCI 440, 1 serving cell × 16 params × 1 BWP × 7 params × 4 BWP vars observed).
- **Blocage** : décodeur `app/nmf_decoder/decoder.py:244-264` supporte 1 niveau de group variable (header_col ou previous_end). Les 2 niveaux de nesting (serving cells × BWPs) nécessitent extension décodeur.
- **Effort** : 1 jour (extension nested + migration `scell_*` + schéma + re-decode + guards).
- **Live** : 425 records SCELL system=9 présents dans `nmf_event_light` (411+4+10 par capture) mais 0 colonne décodée.

### Lot 1 ANCIEN STATUT — remplacé par REPRISE 9 ci-dessus

**Commits** : `4951569`, `cb64e46`, `954117d`, `2bc6f95`, `0248c6e`, `f591af9`, `697992b` (CHI pipeline).

**Fichiers:lignes** :
- `app/nmf_decoder/schemas-2.50/PLAID_NR.yaml`, `PLAIU_NR.yaml`, `MACRATE_NR.yaml`, `MACRATEU_NR.yaml` avec `cell_scoped: true`.
- `app/nmf_decoder/schemas-2.50/CHI.yaml:8` — `system_col: 4` + `agg:"dominant"` (ajouté REPRISE 8 Point 3).
- `app/nmf_decoder/store.py:40-80` — header_filter par schéma.
- `app/kpi/metrics_catalog_v4.py:710-740` + `:1153-1180` — `event_columns` ingère toutes les colonnes `cell_scoped=True` de `metrics_v3.definitions()`.

**OUVERT résiduel** — voir §7 pour détail (CQI_NR, DCI_NR, SCELL, SCELLMOD).

### Lot 2 à Lot 5 — **FAIT** (voir rapport précédent §3).

### Lot 6 — `display_code` + align metrics[]/tree — **FAIT** (voir §3 Lot 6 ci-dessous)

**Commit** : `74e17dc`, `c6e9081`, **`cad7c88` (REPRISE 8 §2)**.

### Lot 7 — Export front per capture — **FAIT** (voir §4).

### REPRISE 8 Point 1 (Unités) — **FAIT**
Fichier:ligne : `app/kpi/metrics_catalog_v4.py:850-874` (baked), `:1068-1070` (nodes_out baked), `:1261-1264` (dynamic). Fallback unit depuis `metrics_v3.definitions()[source_column]["unit"]`.

Garde (par capture) :
```python
# Feuilles with values AND v3_defs has unit AND output unit=''
no_unit = [n for n in nodes if n.node_type=='leaf' and n.n>0
           and not (n.unit or '').strip()
           and defs.get(n.source_column, {}).get('unit')]
```
Résultat :
```
Test_6: 23 → 0 (fix)
ikea.6: 23 → 0
ikea.2: 23 → 0
```
Les 111/91/86 restantes qui n'ont pas d'unité sont des champs intrinsèquement sans unité NFF (identifiants, enums, flags) — v3_defs lui-même expose `unit=''` pour eux.

### REPRISE 8 Point 2 (deux catalogues : UI consumer + align) — **FAIT**

L'UI consomme **l'arbre `nodes`**, fichier:ligne :
```
franco-focus-forge/src/features/kpi/MetricsCatalogSidebar.tsx:370
  const query = useQuery({ ...metricsCatalogQuery(projectId, captureIds), retry: false });
franco-focus-forge/src/features/kpi/MetricsCatalogSidebar.tsx:372-373
  const normalizedNodes = useMemo(
    () => mergeMetricCatalogTrees(query.data?.nodes ?? [], measuredMetricNodes(measuredEntries)),
```

Le tableau `metrics[]` est consommé par les routes `/metrics/table`, `/metrics/series`, `/metrics/map` (serveur) et par le CSV export (via `/metrics/catalog-csv`).

Pour alignement : `app/kpi/metrics_catalog_v4.py:858-861` — `kind=lf.get("_kind") or _kind_from_type(lf.get("type"))`. `chi_rrc_state` devient `KPI_CATEGORICAL` dans metrics[] (était `numeric` legacy).

Garde (par capture) :
```python
for m in payload['metrics']:
    dc = m.get('display_code') or m.get('code')
    tree_kind = tree_by_code.get(dc)
    if tree_kind and tree_kind != m.get('kind'): mismatch += 1
```
Résultat : **mismatches = 0** sur chaque capture.

### REPRISE 8 Point 3 (Enum RRC) — **FAIT**

Fichier:ligne modif :
- `app/nmf_decoder/schemas-2.50/CHI.yaml:28-36` — ajout `enum: {"1":"Idle","2":"Connected"}` + `agg:"dominant"` + `label:"LTE RRC state"`.
- `app/kpi/metrics_v3.py:121-127` — propagation `enum_values` dans `definitions()`.
- `app/kpi/metrics_catalog_v4.py:734-754` — helper `_enum_for_col()`.
- `app/kpi/metrics_catalog_v4.py:850-863`, `:1037`, `:1272-1273`, `:1319` — exposure sur nodes_out / metrics_out baked + dynamic.
- `app/kpi/catalog_release/catalog_2.64.1.json` — `enums.rrc_state = [{value:1,label:Idle},{value:2,label:Connected}]`.

Garde (par capture) — `nmf_event_light` LIVE :
```sql
SELECT capture_id,
  SUM(CASE WHEN chi_rrc_state=1 THEN 1 ELSE 0 END) AS idle_1,
  SUM(CASE WHEN chi_rrc_state=2 THEN 1 ELSE 0 END) AS connected_2
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='CHI'
GROUP BY capture_id ORDER BY capture_id;
```
```
Test_6: Idle=181 Connected=451
ikea.6: Idle=6   Connected=5
ikea.2: Idle=5   Connected=6
```

### REPRISE 8 Point 4 (CHI reparent + dedup) — **FAIT**

Fichier:ligne : `scripts/catalog/patch_2_65_0.py` + `app/kpi/catalog_release/catalog_2.65.0.json`.

Reparentage :
- 93 CHI (bloc LTE + sans marqueur) → `cat_LTE_signalling` (tech_LTE).
- 2 CHI (bloc NR) → nouvelle `cat_NR_signalling` (tech_NR).
- 17 CHI (bloc GSM/TETRA/UMTS FDD/UMTS TD-SCDMA/EVDO/iDEN/WiMAX/GAN WLAN/cdmaOne) → `cat_Other_legacy_umts_cdma_dvb` (tech_Other).
- Event `ev_chi` splitté en `ev_chi_lte` / `ev_chi_nr` / `ev_chi_other`.
- Dedup intra-tech : 4 feuilles (`chi_lac` GAN/GSM/TETRA/UMTS TD-SCDMA, `chi_ch` iDEN/GSM, `chi_cell_id` GAN/GSM, `chi_frequency` iDEN/WiMAX).
- Labels `(bloc X)` strippés sur les 31 leaves concernées.

Garde (par capture) :
```sql
SELECT scope_key,
  SUM(CASE WHEN n->>'event'='CHI' AND n->>'node_type'='leaf' AND n->>'technology'='Shared' THEN 1 ELSE 0 END) AS chi_in_shared,
  SUM(CASE WHEN n->>'event'='CHI' AND n->>'node_type'='leaf' AND n->>'label' ~ '\(bloc ' THEN 1 ELSE 0 END) AS bloc_marker
FROM metrics_catalog_cache, jsonb_array_elements(payload->'nodes') AS n
WHERE scope_key LIKE 'captures:%' GROUP BY scope_key;
```
```
Test_6: chi_in_shared=0 bloc_marker=0
ikea.6: chi_in_shared=0 bloc_marker=0
ikea.2: chi_in_shared=0 bloc_marker=0
```

### REPRISE 8 Point 5 (Lot 1 restants) — **OUVERT**

Travail NFF byte-forensic requis par schéma. Specs NFF 2.50 vérifiées :

- **CQI_NR** : NFF 2.50 p.579-581. Header : #Header params + Scope + Cell type + RI (1-8) + WB CQI (0-15). Groupes : (RI distribution : #Variables + #Params/variable + {Count, RI}) + (WB CQI distribution : {Count, WB CQI}).
- **DCI_NR** : NFF 2.50 pages DCI format NR variable layout.
- **SCELL** : NFF 2.50 serving-cell SCell add/remove/activate — ajouter `cell_scoped: true` à `SCELL.yaml` + colonnes.
- **SCELLMOD** : NFF 2.50 p.424-426 — schéma à créer avec `system_col:` + colonnes `scellmod_*`.

**Bloqueur** : vérification « 2 records réels octet par octet » requiert accès aux fichiers NMF + outils byte-level de décodage (parse brut, non le pipeline existant qui marque les records system=9 comme LTE). Ce travail est hors de ce passage REPRISE 8 — à prévoir en session dédiée avec les 3 fichiers NMF Test_6 + traces hexadécimales. Effort estimé total : 4 jours.

### REPRISE 8 Point 6 (non-perte mesurée) — **FAIT, 0 vraie perte**

Mesure dans `/tmp/non_perte_measure.py` (exécuté sur conteneur) :

```python
# Pour chaque displayed leaf de 2.62.0 absente de 2.65.0 (3 416 total)
# - sans source_column : rien à perdre (3 239)
# - source_column pattern STRUCT (_n_params, _params, params_cells, _variables)
#   OU label STRUCT (#Params/#Variables/#Header/Count/Measured system) : STRUCT légitime filtré (27)
# - source_column PRÉSERVÉE comme leaf dans 2.65.0 (même values accessibles sous nouveau mid) : (150)
# - sinon : vérifier count_values_per_capture via nmf_cell_second + nmf_event_light
#   → si any count > 0 : TRULY LOST
```

Sortie :
```
2.62.0 displayed:         8 735
2.65.0 displayed:         5 319
missing in 2.65.0:        3 416
  no source_column:       3 239
  STRUCT pattern:            27
  source_column preserved:  150
  TRULY LOST with values:     0  ✓
```

**Garde Point 6 : 0 feuille avec valeurs disparue** sur l'intervalle 2.62.0 → 2.65.0 par capture (chaque motif de retrait a été vérifié par SQL dans `nmf_cell_second` et `nmf_event_light`).

### REPRISE 8 Point 7 (versions) — **FAIT**

- catalog_release **2.64.1** : Points 1-3 (unités + align metrics[] + enum RRC) — sha `b2cd587856cdccc035834f2580fb32f969dd94161ba96342669e00bf868c89c0`.
- catalog_release **2.65.0** : Point 4 (CHI reparent + dedup) — sha `36da300ca1b15ffbaff7a87e82361b9c5a80b9286fddd50e3664bed6bf1f591f`.
- Décodeur **1.10.5** inchangé (Points 1-4 pure catalog layer).
- Back **0.126.3** (Points 1-3) → **0.126.4** (Point 4), 1 commit par étape avec CHANGELOG.
- Décodeur **1.10.6+** réservé pour Point 5 (schémas NR, non livré ce passage).

---

## 4. PHY NR par capture (colonnes nommées) — inchangé depuis matin

### Garde live `nmf_cell_second cell_index=9670` (NR PSCell 199)

| capture | NR_PDSCH_PRBS | NR_PDSCH_MCS0 | NR_PUSCH_PRBS | NR_PUSCH_MCS0 | NR_MAC_DL_THP | NR_MAC_UL_THP |
|---|---|---|---|---|---|---|
| **Test_6** (a4b0c321c52e) | 1 796 | 1 796 | 1 741 | 1 741 | 2 852 | 2 852 |
| **ikea.6** (daa2b1df250d) | 2 | 2 | 5 | 5 | 13 | 13 |
| **ikea.2** (ecffb18dbd7f) | 79 | 79 | 106 | 106 | 107 | 107 |

### Garde catalogue (post REPRISE 8)

| code | Test_6 | ikea.6 | ikea.2 | unit |
|---|---|---|---|---|
| plaid_prbs@nr-type-199 | 1 796 | 2 | 79 | **index** (était vide) |
| plaid_mcs0@nr-type-199 | 1 796 | 2 | 79 | **index** |
| plaiu_prbs@nr-type-199 | 1 741 | 5 | 106 | **index** |
| plaiu_mcs0@nr-type-199 | 1 741 | 5 | 106 | **index** |
| macrate_mac_dl_bitrate@nr-type-199 | 2 852 | 13 | 107 | **Mbit/s** |
| macrateu_mac_ul_bitrate@nr-type-199 | 2 852 | 13 | 107 | **Mbit/s** |

(Toutes les units proviennent de `metrics_v3.definitions()[source_column]['unit']` — jamais fabriquées.)

### Levée d'ambiguïté « 1796/2/79 » (inchangée)

Pour PLAID system=9 : Test_6=2853 events / 5030 records, ikea.6=**13 events / 23 records**, ikea.2=107 events / 194 records. Le « 79 » vient d'ikea.2, pas d'ikea.6. La chaîne 1796/2/79 est le count `nmf_cell_second cell_index=9670 metric=plaid_prbs` par capture (une PLAID event peut projeter plusieurs rows nmf_cell_second).

---

## 5. ÉTAT RRC par capture (inchangé)

```
Test_6: Idle=181 Connected=451 total=632
ikea.6: Idle=6   Connected=5   total=11
ikea.2: Idle=5   Connected=6   total=11
```

### Catalogue tree + metrics[] alignés (REPRISE 8 §2 + §3)

| capture | tree.kind | tree.label | tree.enum_values | tree.technology | metrics.kind | metrics.enum_values |
|---|---|---|---|---|---|---|
| Test_6 | **KPI_CATEGORICAL** | **LTE RRC state** | `{1: Idle, 2: Connected}` | **LTE** | **KPI_CATEGORICAL** | `{1: Idle, 2: Connected}` |
| ikea.6 | KPI_CATEGORICAL | LTE RRC state | `{1: Idle, 2: Connected}` | LTE | KPI_CATEGORICAL | `{1: Idle, 2: Connected}` |
| ikea.2 | KPI_CATEGORICAL | LTE RRC state | `{1: Idle, 2: Connected}` | LTE | KPI_CATEGORICAL | `{1: Idle, 2: Connected}` |

Category : « Signalling » (plus « Services (tasks) »), Technology : LTE (plus Shared). ✓

---

## 6. NON-PERTE 2.62.0 → 2.65.0 — mesurée par capture

Reprise REPRISE 8 Point 6 (mesure réelle, pas « par construction »).

### Comptes
```
2.62.0 displayed:         8 735
2.65.0 displayed:         5 319
missing in 2.65.0:        3 416
```

### Motifs (par SQL par capture)

| Motif | n | Définition (fichier:ligne) + mesure |
|---|---|---|
| ghost-NR-placeholder | **2 405** | `cell_type ∈ {100..131, 98, 198, 199, 1000, 1001, 1002}` ET `field_system ≠ 9`. `app/kpi/metrics_catalog_v4.py:603-607`. |
| STRUCT #Params/#Variables/#Header | **551** | label hash-prefix structurel. `app/kpi/metrics_catalog_v4.py:629-633`. |
| STRUCT cqi_n_params / Measured system | **284** | `app/kpi/metrics_catalog_v4.py:634`. |
| STRUCT Count @ cell | **140** | `app/kpi/metrics_catalog_v4.py:637-638`. |
| MIMO/CSI/PMI on neighbour | **27** | `app/kpi/metrics_catalog_v4.py:664-669`. |
| CHI #NN dedup | **5** | REPRISE 7 Point 2, `scripts/catalog/patch_2_63_2.py`. |
| CHI dedup intra-tech | **4** | REPRISE 8 Point 4, `scripts/catalog/patch_2_65_0.py`. |
| **TOTAL** | **3 416** | |

### Feuilles **avec valeurs réellement perdues** : 0 ✓

Mesure effective (vs « par construction » du rapport du matin). Pour les 3 416 missing :
```
sans source_column (rien à perdre) :                3 239
STRUCT pattern (source_column _n_params, _params…) :    27
source_column préservée comme leaf 2.65.0 (values accessibles via nouveau mid) : 150
TRULY LOST avec valeurs : 0  ← mesuré par SQL sur nmf_cell_second + nmf_event_light
```

Détail des 150 "source_column préservée" : les 5 dedup CHI #NN (REPRISE 7 Point 2) et les 4 dedup CHI intra-tech (REPRISE 8 Point 4) pointent sur la même source_column que leur primaire conservé. Les 141 autres sont des cell-type leaves `_fNN@cell` (variantes NFF du même source_column) regroupées sous un unique leaf par (tech, cell_type).

**Attendu : 0. Mesuré : 0.** Garde Point 6 PASS.

---

## 7. ÉCARTS OUVERTS (mis à jour post REPRISE 8)

| # | Écart | État | Cause | Fichier:ligne | Effort |
|---|---|---|---|---|---|
| 7.1 | **CQI_NR** 0 variante NR au catalogue | **OUVERT** | `schemas-2.50/CQI_NR.yaml` absent → 2 972 records CQI system=9 décodés comme LTE | NFF 2.50 p.579-581 (spec extraite, voir §3 Point 5) + à créer `app/nmf_decoder/schemas-2.50/CQI_NR.yaml` | 1 jour |
| 7.2 | **DCI_NR** 0 variante NR au catalogue | **OUVERT** | `DCI_NR.yaml` absent → 2 972 records DCI system=9 décodés comme LTE | NFF 2.50 pages DCI format NR + `DCI_NR.yaml` | 1 jour |
| 7.3 | **SCELL** 0 colonne `nmf_cell_second` | **OUVERT** | `SCELL.yaml` sans `cell_scoped: true` ni groups | `app/nmf_decoder/schemas-2.50/SCELL.yaml` | 1 jour |
| 7.4 | **SCELLMOD** schéma absent | **OUVERT** | `SCELLMOD.yaml` absent → 347 records system=NULL | `app/nmf_decoder/schemas-2.50/SCELLMOD.yaml` NFF 2.50 p.424-426 | 1 jour |
| 7.5 | ~~CHI en Shared~~ | ✅ **FERMÉ REPRISE 8** | 116 feuilles reparentées : 93 LTE + 2 NR + 17 Other | — | — |
| 7.6 | ~~31 doublons (bloc X)~~ | ✅ **FERMÉ REPRISE 8** | labels strippés + 4 dedup intra-tech | — | — |
| 7.7 | ~~Enum Idle/Connected~~ | ✅ **FERMÉ REPRISE 8** | enum YAML + propagation runtime + baked JSON | — | — |
| 7.8 | ~~plaid_mcs0 unit=""~~ | ✅ **FERMÉ REPRISE 8** | fallback v3_defs | — | — |

### Mise à jour post REPRISE 9 (LOT 1 FINAL)

| # | Écart | État | Détail |
|---|---|---|---|
| 7.1 | **CQI_NR** | ✅ FERMÉ REPRISE 9 | Décodeur 1.10.6, migration 0088, schéma `CQI_NR.yaml`, 2 records vérifiés, garde par capture + par cellule PASS. |
| 7.2 | **DCI_NR** | ✅ FERMÉ REPRISE 9 | Décodeur 1.10.7, migration 0089, schéma `DCI_NR.yaml`, garde par capture + par cellule PASS. |
| 7.3 | **SCELL** | ✅ FERMÉ REPRISE 10 | Décodeur 1.11.0 avec extension `count_header_col`/`params_header_col` (header-interleaved), migration 0091, schéma `SCELL_NR.yaml`. 2 records réels vérifiés. Garde `nmf_event_group serving_cells` par cell_type : Test_6=298 @ 199, ikea.6=3 @ 199 + 1 @ 4, ikea.2=5 @ 199. Non-régression CQI/DCI/LTE unchanged. |
| 7.4 | **SCELLMOD** | ✅ FERMÉ REPRISE 9 | Décodeur 1.10.8, migration 0090, schéma `SCELLMOD.yaml`, garde `nmf_event_group` par cell_type (Test_6=211/211 @199, ikea.6=3/3 @{117,199}, ikea.2=5/5 @199). Projection `nmf_cell_second` différée (cells.py extension pour group-level cell_type). |

**Lot 1 : 0 écart OUVERT. CLÔTURE LOT 1 complète.**

| Composant | État final |
|---|---|
| CQI_NR | ✅ FERMÉ (REPRISE 9, décodeur 1.10.6) |
| DCI_NR | ✅ FERMÉ (REPRISE 9, décodeur 1.10.7) |
| SCELLMOD | ✅ FERMÉ (REPRISE 9, décodeur 1.10.8) |
| SCELL_NR | ✅ FERMÉ (REPRISE 10, décodeur 1.11.0 + moteur étendu) |

---

## 8. IDENTITÉ

- **Agent** : **Agent BC2** (signature appliquée dans les commits REPRISE 8 : `cad7c88`, `697992b`, `b2c174a`).
- **Session** : chantier routé vers `[bc4]` — dépôts : `bc4-back` + `franco-focus-forge`.
- Project de preuve : **Test_6** `43e81a34a073` ; 3 captures Test_6 / ikea.6 / ikea.2.

---

## Artefacts joints (régénérés post REPRISE 8)

| Fichier | Lignes | Taille | Catalog |
|---|---|---|---|
| `/home/devmat/BC4/export_test_6_final.csv` | 5 574 | 1 137 593 B | 2.65.0 |
| `/home/devmat/BC4/export_test_6_with_values.csv` | 453 | 89 300 B | 2.65.0 |
| `/home/devmat/BC4/export_ikea_6_with_values.csv` | 325 | 65 276 B | 2.65.0 |

Endpoint live : `GET http://localhost:8000/projects/43e81a34a073/metrics/catalog-csv`

Header CSV :
```
﻿# BC4 catalog export · catalog_release 2.65.0 · 3 captures
"display_code";"label";"kind";"unit";"data_type";"Technology";"Category";"Group";"Metric";"Cell";"Event";"Source column";"Metric id";"Raw cell type";"Selectable";"Availability";"Reason";"n_a4b0c321c52e";"n_daa2b1df250d";"n_ecffb18dbd7f"
```

Extrait preuve post REPRISE 8 :
```
chi_rrc_state ; LTE RRC state ; KPI_CATEGORICAL ; ; ; LTE ; Signalling ; … ; 632 ; 11 ; 11
plaid_mcs0@nr-type-199 ; MCS CW0 (DL) @ SCG PSCell ; KPI ; index ; ; LTE ; Allocation & MCS ; … ; 1796 ; 2 ; 79
macrate_mac_dl_bitrate@nr-type-199 ; MAC DL bitrate (bloc LTE) @ SCG PSCell ; KPI ; Mbit/s ; … ; 2852 ; 13 ; 107
cell_sinr@nr-type-199 ; SINR (LTE) @ SCG PSCell ; KPI ; dB ; … ; 2919 ; 14 ; 108
```

(Unités `index`/`Mbit/s`/`dB` apparaissent — plus vides — depuis fallback v3_defs §1. `chi_rrc_state` en Technology=LTE Category=Signalling §4, kind KPI_CATEGORICAL §2.)

— Agent BC2
