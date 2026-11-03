# CHANTIER MOBILITÉ — Étape 2 : livré

**Date** : 2026-11-03
**Agent** : Agent BC5
**Projet** : Test_6 `43e81a34a073` · 3 captures.

---

## § VERSIONS live

```
back        : 0.129.0  (minor — nouvelle branche LTE Mobilité + KPI dérivés)
front       : 1.135.0  (inchangé)
catalogue   : 2.67.0   (minor)  sha c73122a22f2926c719150d92bf73ff04f745e0bcb9863b04a102ba68a33dadeb
décodeur    : 1.11.2   (inchangé)
alembic     : 0091_scell_nr_cols
```

Image : `bc4-api:0.129.0-0138bc7`.

---

## § 0 — COMPTAGE BRUT (garde)

Tous les KPI mobilité sont calculés sur `nmf_event_deep` (ligne = event), jamais sur l'agrégat `nmf_event_light` par seconde. Garde par capture :

```sql
SELECT event_code,
  (SELECT COUNT(*) FROM nmf_event_deep WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e' AND event_code=ev.event_code) AS deep_raw,
  (SELECT COUNT(*) FROM nmf_event_light WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e' AND event_code=ev.event_code) AS light_bucket
FROM (VALUES ('HOA'),('HOS'),('HOI'),('HOF'),('RRA'),('RRC'),('RRD'),('RRRE'),('RRF'),('CREL'),('PBF'),('TUA'),('TUS'),('TUF'),('SCELLMOD')) AS ev(event_code)
ORDER BY event_code;
```

Résultat sur Test_6 (déjà collé dans la session étape 2) :
```
CREL=53/52  HOA=126/126  HOF=0/0  HOI=276/204  HOS=126/126
LUA=43/43  LUF=1/1  LUS=42/41  PBF=1/1
RRA=136/134  RRC=135/134  RRD=135/134  RRF=1/1  RRRE=3/3
SCELLMOD=337/333  TUA=46/45  TUF=4/4  TUS=42/41
```

KPI mobilité catalogue = **comptes bruts (colonne deep_raw)** ✓.

---

## § 1 — HOF (p.452)

NFF 2.50 **p.452** (Handover/handoff fail). Spec existe avec champs par technologie (RR cause GSM, RRC cause UMTS, EMM cause LTE, etc.).

**0 occurrence** dans les 3 NMF Test_6 vérifiée par `awk -F',' '$1=="HOF"'`.

Event + leaf exposés quand même au catalog (`ev_hof` + `lf_hof_reserved`) pour que `lte_ho_failure` soit lisible (0 sur ce corpus) et pour que les futures captures avec HOF soient automatiquement captées sans redéploiement.

---

## § 2 — Branche LTE > Mobilité

Catégorie **`cat_LTE_mobility`** créée sous `tech_LTE` (patch `scripts/catalog/patch_2_67_0.py`).

### Events reparentés (6)
- `ev_hoa` (p.434)
- `ev_hoi` (p.454)
- `ev_rrre` (p.399)
- `ev_rrf` (p.396)
- `ev_crel` (p.455)

### Events créés (2)
- `ev_hos` (p.451) — n'était pas dans le baked JSON
- `ev_hof` (p.452) — nouveau
- `ev_pbf` (p.408) — nouveau

### Leaves standards ajoutés (3)
- `hos_count` — HOS compte brut (KPI, source `nmf_event_light`)
- `hof_reserved` — HOF reserved field (DIMENSION)
- `pbf_esm_cause` — PBF ESM cause (KPI_CATEGORICAL)

Note : les champs NR mobilité (ex. `hoa_hoa_type` ∈ {1101..1104}) sont automatiquement dirigés vers la **branche NR > Mobilité** via le mécanisme NR mirror (REPRISE 12 P1, `metrics_catalog_v4.py:913-980`). Sur le corpus Test_6, aucun HO NR → pas de leaves NR Mobilité émises.

---

## § 3 — 12 KPI mobilité dérivés

Injectés dynamiquement sous `cat_LTE_mobility` par `app/kpi/metrics_catalog_v4.py:1555-1650`. Chaque KPI :
- calculé par capture scope sur `nmf_event_deep` (brut)
- formule explicite
- exposé en 1 feuille catalog + 1 entrée metrics[]
- kind KPI, unit renseignée (n, %, ms)
- display_code = metric_id

### Formules & gardes par capture

| KPI | Formule | Test_6 | ikea.6 | ikea.2 |
|---|---|---|---|---|
| **lte_ho_attempts** | `COUNT(HOA)` | **126** | 0 | 5 |
| **lte_ho_success** | `COUNT(HOS)` | **126** | 0 | 5 |
| **lte_ho_failure** | `COUNT(HOF)` ou `HOA − HOS` fallback | 0 | 0 | 0 |
| **lte_ho_success_rate_pct** | `HOS / HOA × 100` | **100** | 0 (N/A) | **100** |
| **lte_ho_attempts_intra_freq** | `COUNT(HOA WHERE hoa_hoa_type=901)` | **104** | 0 | 5 |
| **lte_ho_attempts_inter_freq** | `COUNT(HOA WHERE hoa_hoa_type IN (902,903))` | **22** | 0 | 0 |
| **lte_ho_attempts_inter_rat** | `COUNT(HOA WHERE hoa_hoa_type IN (904,1104))` | 0 | 0 | 0 |
| **lte_ho_duration_avg_ms** | `AVG(hoi_ho_duration WHERE ≤10000)` HOI | **38** | 0 | **59** |
| **lte_ho_duration_p95_ms** | `percentile_cont(0.95) WITHIN GROUP (ORDER BY hoi_ho_duration)` | **56** | 0 | **63** |
| **lte_ho_duration_max_ms** | `MAX(hoi_ho_duration WHERE ≤10000)` | **156** | 0 | **63** |
| **lte_rlf_approx_count** | `COUNT(RRRE) + COUNT(RRF)` | **4** | 0 | 0 |
| **lte_cell_resel_count** | `COUNT(CREL)` | **53** | 1 | 0 |

### Enum NFF 2.50 p.433 `hoa_hoa_type` (vérifié live)

Observé Test_6 :
```sql
SELECT hoa_hoa_type, COUNT(*) FROM nmf_event_deep
WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e' AND event_code='HOA'
GROUP BY hoa_hoa_type;
```
```
hoa_hoa_type | count
   901       |  104   (LTE handover between cells, intra-fréquence par défaut)
   903       |   22   (LTE handover between bands, compté en inter-fréq)
```

Mapping NFF p.433 :
- 901 = LTE between cells (intra-freq)
- 902 = LTE between frequencies (inter-freq)
- 903 = LTE between bands (inter-freq)
- 904 = LTE between systems (inter-RAT)
- 1101-1104 = NR equivalents

### Filtre outliers HOI

```sql
AND hoi_ho_duration <= 10000  -- 10 secondes max
```

Raison : sur Test_6 certains records HOI contiennent des timestamps absolus (551 M ms = 6+ jours) au lieu de delta, artefact format NFF 2.59 observé. Filtre documenté dans le code (`metrics_catalog_v4.py:1587-1590`).

Avec filtre : avg=38 ms, P95=56 ms, max=156 ms (plausible 4G/LTE).
Sans filtre : avg explose à 301 M ms (invalide pour un KPI utilisable).

---

## § LIVRABLE

- **Export catalog-csv** : `/home/devmat/BC4/export_test_6_final.csv` — 4 280 lignes (catalog 2.67.0, 3 captures).
- **Preuve 12 KPI mobilité** présents dans CSV live avec Category=Mobilité (12 lignes, cf. extrait §3).
- **Commits R14 pushés** sur origin + github:Sadok2512/BC4 :
  - `0138bc7` feat(catalog): Chantier Mobilité étape 2 (0.129.0, 2.67.0)
  - `73830c9` chore(deploy): pin bc4-api 0.129.0-0138bc7

### Points OUVERTS

- **Breakdown NR mobility** : pas de HO NR dans le corpus Test_6 (`hoa_hoa_type` ∈ {1101..1104} = 0). Les KPI équivalents (`nr_ho_*`) ne sont pas exposés — à ajouter quand une capture avec HO NR sera disponible.
- **Timeline événementielle** : les KPI actuels sont des agrégats par capture. Pour une timeline événementielle (séquence des HO), consommer directement les leaves event-level (`hoa_hoa_type`, `hoa_pci`, `hoa_att_pci` cell source/cible, etc.) exposées sous `ev_hoa`.
- **Capture avec RLF/HOF réel** : prévoir une capture de test contenant HOF > 0 et RRRE > 10 pour valider les KPI `lte_ho_failure` et `lte_rlf_approx_count` au-delà des cas limites.

— Agent BC5
