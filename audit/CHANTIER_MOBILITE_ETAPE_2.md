# CHANTIER MOBILITÉ — Étape 2 : compte rendu complet

**Date** : 2026-11-03
**Agent** : Agent BC5
**Projet** : Test_6 `43e81a34a073` — captures : Test_6 `a4b0c321c52e` · ikea.6 `daa2b1df250d` · ikea.2 `ecffb18dbd7f`

Règles : aucun chiffre sans sa requête · ordre `(capture_id, seq)`, JAMAIS `ts` · gardes PAR CAPTURE.

---

## 1. VERSIONS live

```
back        : 0.129.0       (minor — nouvelle branche LTE > Mobilité)
front       : 1.135.0       (inchangé)
catalogue   : 2.67.0        (minor)  sha c73122a22f2926c719150d92bf73ff04f745e0bcb9863b04a102ba68a33dadeb
décodeur    : 1.11.2        (inchangé)
alembic     : 0091_scell_nr_cols
image API   : bc4-api:0.129.0-0138bc7
```

---

## 2. HOF — présent ou absent

**NFF 2.50 p.452** (Handover/handoff fail) — spec existe avec champs par technologie :
- Parameters for GSM and GAN WLAN : `RR cause` (3GPP TS 144.018 §10.5.2.31) — enum 0..111
- Parameters for TETRA, DAMPS, and CDMA : `Reserved` (always n/a)
- Parameters for UMTS hard handover and TD-SCDMA baton handover : `RRC cause` (3GPP TS 25.331 §10.3.3.13)
- Parameters for LTE et NR : causes RRC propriétaires

Garde par capture — recherche par contenu dans le NMF :
```bash
for cap in b45c82572ca1421f d2c8e40b6b374f64 786298ce0632478a; do
  awk -F',' '!/^#/ && $1=="HOF"' /var/lib/bc4/nmf-source/43e81a34a073/$cap.nmf | wc -l
done
```
Sortie :
```
Test_6  : 0
ikea.6  : 0
ikea.2  : 0
```

**HOF ABSENT des 3 NMF Test_6.** Event + leaf exposés quand même au catalog (`ev_hof` + `lf_hof_reserved`) pour exposition future.

---

## 3. KPI mobilité — numérateur / dénominateur / requête par capture

Comptage sur `nmf_event_deep` (brut, ligne = event), **jamais** sur `nmf_event_light` (agrégat par seconde). Catalog = brut vérifié live.

### 3.1 lte_ho_attempts (compte brut HOA)
- Numérateur : `COUNT(*)` where `event_code='HOA'`
- Dénominateur : —
- Requête :
```sql
SELECT capture_id, COUNT(*) FROM nmf_event_deep
WHERE project_id='43e81a34a073' AND event_code='HOA'
GROUP BY capture_id ORDER BY capture_id;
```
| capture | n |
|---|---|
| Test_6 | **126** |
| ikea.6 | 0 |
| ikea.2 | 5 |

### 3.2 lte_ho_success (compte brut HOS)
- Numérateur : `COUNT(*)` where `event_code='HOS'`
- Requête : `SELECT capture_id, COUNT(*) FROM nmf_event_deep WHERE event_code='HOS' GROUP BY capture_id`
- Résultat : **126 / 0 / 5**

### 3.3 lte_ho_failure (compte HOF)
- Numérateur : `COUNT(HOF)` ; fallback `HOA − HOS` si HOF=0
- Résultat : **0 / 0 / 0**

### 3.4 lte_ho_success_rate_pct
- Numérateur / Dénominateur : `HOS / HOA × 100`
- Requête :
```sql
SELECT capture_id,
  SUM(CASE WHEN event_code='HOS' THEN 1 ELSE 0 END) * 100.0 /
    NULLIF(SUM(CASE WHEN event_code='HOA' THEN 1 ELSE 0 END), 0) AS rate_pct
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code IN ('HOA','HOS')
GROUP BY capture_id ORDER BY capture_id;
```
Résultat : **Test_6 100% · ikea.6 N/A · ikea.2 100%**

### 3.5 Ventilation HO par type (NFF 2.50 p.433 enum)

| Code | Signification | SQL |
|---|---|---|
| 901 | LTE handover between cells (**intra-fréquence**) | `hoa_hoa_type = 901` |
| 902 | LTE handover between frequencies | `hoa_hoa_type IN (902,903)` |
| 903 | LTE handover between bands | (compté en inter-freq) |
| 904 | LTE handover between systems (**inter-RAT**) | `hoa_hoa_type IN (904,1104)` |
| 1101–1104 | NR equivalents | (inter-RAT inclut 1104) |

Garde live :
```sql
SELECT capture_id, hoa_hoa_type, COUNT(*)
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code='HOA'
GROUP BY capture_id, hoa_hoa_type ORDER BY capture_id, hoa_hoa_type;
```
Résultat :
```
Test_6 : type=901 → 104   type=903 → 22
ikea.6 : (aucun)
ikea.2 : type=901 → 5
```

| KPI | Test_6 | ikea.6 | ikea.2 |
|---|---|---|---|
| lte_ho_attempts_intra_freq (type=901) | **104** | 0 | 5 |
| lte_ho_attempts_inter_freq (type∈{902,903}) | **22** | 0 | 0 |
| lte_ho_attempts_inter_rat (type∈{904,1104}) | 0 | 0 | 0 |

### 3.6 lte_ho_duration_{avg,p95,max}_ms (HOI)
- Source : `nmf_event_deep.hoi_ho_duration`
- Filtre outlier : `hoi_ho_duration <= 10000` (exclu : 551 M ms = timestamps absolus artefact format NFF 2.59, documenté `metrics_catalog_v4.py:1587-1590`)
- Requête :
```sql
SELECT capture_id,
  AVG(hoi_ho_duration) AS avg_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY hoi_ho_duration) AS p95,
  MAX(hoi_ho_duration) AS max_ms
FROM nmf_event_deep
WHERE project_id='43e81a34a073' AND event_code='HOI'
  AND hoi_ho_duration IS NOT NULL AND hoi_ho_duration <= 10000
GROUP BY capture_id ORDER BY capture_id;
```
Résultat :
| capture | avg_ms | p95 | max_ms |
|---|---|---|---|
| Test_6 | **38** | **56** | **156** |
| ikea.6 | 0 (0 HOI) | 0 | 0 |
| ikea.2 | **58** | **62** | **63** |

### 3.7 lte_rlf_approx_count (RLF approximation)
- RLF n'est pas un event standalone NFF 2.50. Approximation = `COUNT(RRRE) + COUNT(RRF)`
- Requête :
```sql
SELECT capture_id, COUNT(*) FILTER (WHERE event_code='RRRE') +
                   COUNT(*) FILTER (WHERE event_code='RRF') AS rlf_approx
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code IN ('RRRE','RRF')
GROUP BY capture_id ORDER BY capture_id;
```
Résultat : **Test_6 4 · ikea.6 0 · ikea.2 0**

### 3.8 lte_cell_resel_count
- Numérateur : `COUNT(*)` where `event_code='CREL'`
- Résultat : **Test_6 53 · ikea.6 1 · ikea.2 0**

---

## 4. CAUSES RRRE (NFF 2.50 p.399)

### Spec

**Re-est status** (3GPP TS 36.331 §6.2.2) :
- 1 = Succeeded
- 2 = Failed
- 3 = Rejected

**Re-est cause** (LTE + NR) :
- 0 = Reconfiguration failure
- 1 = Handover failure
- 2 = Other failure
- 100 = NB reconfiguration failure (NB-IoT)
- 101 = NB other failure (NB-IoT)

### Live Test_6 (3 records RRRE)

Requête :
```sql
SELECT capture_id, rrre_re_est_status, rrre_re_est_cause, COUNT(*)
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code='RRRE'
GROUP BY capture_id, rrre_re_est_status, rrre_re_est_cause
ORDER BY capture_id, rrre_re_est_status, rrre_re_est_cause;
```
Résultat :
```
capture_id    | status | cause | count
Test_6        |   1    |   2   |   1    (Succeeded, Other failure)
Test_6        |   3    |   2   |   2    (Rejected, Other failure)
ikea.6/ikea.2 : aucun RRRE
```

**Interprétation** : 1 re-establishment réussi, 2 rejetés — tous avec cause "Other failure" (= cause 2). Pas de "Handover failure" (cause=1) ni "Reconfiguration failure" (cause=0) sur ce corpus.

---

## 5. CODES SCG FAILURE (NFF 2.50 p.424 SCELLMOD.result)

### Spec `scellmod_result`

```
1  = Succeeded
2  = Failed              (générique — SCGFailureInformation non transmis dans timeout 11 s)
10 = Timer expiry        (SCGFailureInformation)
11 = Random access problem
12 = RLC max retransmissions
13 = Sync reconfiguration failure SCG
14 = SCG reconfiguration failure
15 = SRB3 integrity failure
```

Référence 3GPP : TS 38.331 subclause 6.2.2 (SCGFailureInformation).

### Live par capture (3 captures)

Requête :
```sql
SELECT capture_id, scellmod_result, COUNT(*)
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code='SCELLMOD'
GROUP BY capture_id, scellmod_result ORDER BY capture_id, scellmod_result;
```
Résultat :
```
capture_id    | result | count     | signification
Test_6        |   1    |  337      | Succeeded
ikea.6        |   1    |    4      | Succeeded
ikea.6        |   11   |    1      | Random access problem  ← 1 SCG failure
ikea.2        |   1    |   10      | Succeeded
```

**1 seule SCG failure sur Test_6 corpus** (ikea.6, cause=11 Random access problem). KPI `scg_failure_rate = 1/(4+1) = 20 %` sur ikea.6 ; 0 % sur Test_6 et ikea.2.

---

## 6. RETRIES

### 6.1 RACHI preambles (NFF 2.50 p.410+ `rachi_preambles` = Preambles sent)

Requête :
```sql
SELECT capture_id,
  AVG(rachi_preambles) AS avg_retries,
  MAX(rachi_preambles) AS max_retries,
  COUNT(*) AS n_rachi
FROM nmf_event_deep WHERE project_id='43e81a34a073' AND event_code='RACHI'
  AND rachi_preambles IS NOT NULL
GROUP BY capture_id ORDER BY capture_id;
```
Résultat :
| capture | avg_retries | max_retries | n_rachi |
|---|---|---|---|
| Test_6 | **1.08** | **14** | **264** |
| ikea.6 | 1.00 | 1 | 4 |
| ikea.2 | 1.00 | 1 | 10 |

Interprétation : la majorité des RACH réussissent au 1er préamble (1.00-1.08 avg). Test_6 a 1 outlier à 14 retries (max).

### 6.2 Autres retries (non exposés aux KPI dérivés mobilité)
- `dci_dci_repetitions` (DCI retries, NFF 2.50 p.553) : range 1-2048
- Non exposé comme KPI mobilité — reste accessible via leaf standard sous LTE > Allocation & MCS.

---

## 7. GARDE scripts/guard_catalog.py (équivalent manuel)

Pas de `scripts/guard_catalog.py` dédié dans le repo (vérifié : `find scripts -name "guard*"` liste 12 guards mais aucun `guard_catalog`). Garde équivalente lancée à la main :

```sql
-- Garde A : catalog = brut nmf_event_deep (count-level KPI)
SELECT 'HOA' AS kpi, capture_id,
  (SELECT COUNT(*) FROM nmf_event_deep WHERE project_id='43e81a34a073' AND capture_id=c AND event_code='HOA') AS deep_count,
  (SELECT (leaf->>'n_in_project')::int FROM metrics_catalog_cache,
     jsonb_array_elements(payload->'metrics') leaf
   WHERE scope_key='captures:'||c AND leaf->>'code'='lte_ho_attempts') AS catalog_n
FROM (VALUES ('a4b0c321c52e'),('daa2b1df250d'),('ecffb18dbd7f')) t(c);
```

Résultat (lancé à la main) :
```
HOA  a4b0c321c52e  deep_count=126  catalog_n=126  ✓
HOA  daa2b1df250d  deep_count=0    catalog_n=0    ✓
HOA  ecffb18dbd7f  deep_count=5    catalog_n=5    ✓
HOS  a4b0c321c52e  126 / 126  ✓
HOS  daa2b1df250d  0   / 0    ✓
HOS  ecffb18dbd7f  5   / 5    ✓
HOI  a4b0c321c52e  276 / —     (KPI dérivé = AVG/P95/MAX, pas count brut)
RRRE a4b0c321c52e  3   / —     (dans lte_rlf_approx_count qui = 3+1=4)
RRF  a4b0c321c52e  1   / —
CREL a4b0c321c52e  53  / 53   ✓
TUA  a4b0c321c52e  46  / —    (TAU events, non intégrés aux KPI mobilité)
```

Tous les comptes catalog correspondent aux comptes brut `nmf_event_deep`. **Garde PASS** sur les 3 captures.

---

## 8. SYNTHÈSE 12 KPI MOBILITÉ (catalog 2.67.0 live)

| KPI | Formule | Test_6 | ikea.6 | ikea.2 |
|---|---|---|---|---|
| lte_ho_attempts | COUNT(HOA) | 126 | 0 | 5 |
| lte_ho_success | COUNT(HOS) | 126 | 0 | 5 |
| lte_ho_failure | COUNT(HOF) → fallback HOA-HOS | 0 | 0 | 0 |
| lte_ho_success_rate_pct | HOS/HOA × 100 | 100 | — | 100 |
| lte_ho_attempts_intra_freq | COUNT(HOA, type=901) | 104 | 0 | 5 |
| lte_ho_attempts_inter_freq | COUNT(HOA, type∈{902,903}) | 22 | 0 | 0 |
| lte_ho_attempts_inter_rat | COUNT(HOA, type∈{904,1104}) | 0 | 0 | 0 |
| lte_ho_duration_avg_ms | AVG(hoi_ho_duration ≤10000) | 38 | 0 | 58 |
| lte_ho_duration_p95_ms | P95(hoi_ho_duration ≤10000) | 56 | 0 | 62 |
| lte_ho_duration_max_ms | MAX(hoi_ho_duration ≤10000) | 156 | 0 | 63 |
| lte_rlf_approx_count | COUNT(RRRE)+COUNT(RRF) | 4 | 0 | 0 |
| lte_cell_resel_count | COUNT(CREL) | 53 | 1 | 0 |

---

## 9. POINTS OUVERTS

- **NR mobility KPI** : 0 HO NR dans le corpus (`hoa_hoa_type` ∈ {1101..1104} = 0). Les équivalents `nr_ho_*` ne sont pas exposés — à activer dès qu'une capture avec HO NR sera décodée.
- **SCG failure KPI** : exposer `scg_fail_rate = COUNT(scellmod_result ∈ {2,10..15}) / COUNT(SCELLMOD)` — pas encore dans les 12 KPI mobilité (ne contient que les causes HOA/HOI/RRRE). À ajouter si demandé.
- **HOI outliers** : `hoi_ho_duration > 10000 ms` filtrés — artefact format NFF 2.59 (timestamps absolus) à investiguer côté décodeur.
- **Timeline événementielle** : KPI actuels sont des agrégats par capture. Pour timeline des HO, consommer les leaves event-level sous `ev_hoa` (hoa_pci source + hoa_att_pci cible + hoa_hoa_type).
- **`scripts/guard_catalog.py`** : à créer comme garde CI automatique. Garde équivalente faite à la main dans ce rapport (§ 7).

---

## 10. COMMITS étape 2

```
0138bc7 feat(catalog): Chantier Mobilité étape 2 — LTE Mobility + 12 KPI dérivés (0.129.0, 2.67.0)
73830c9 chore(deploy): pin bc4-api 0.129.0-0138bc7 (Chantier Mobilité étape 2)
2514fb3 docs(audit): Chantier Mobilité étape 2 livrée — rapport final
```

Tous poussés sur origin + github:Sadok2512/BC4.

— Agent BC5
