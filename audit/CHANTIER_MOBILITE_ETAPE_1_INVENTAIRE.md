# CHANTIER MOBILITÉ — Étape 1 : inventaire

**Date** : 2026-11-03
**Agent** : Agent BC5
**Projet** : Test_6 `43e81a34a073` — captures : Test_6 `a4b0c321c52e` · ikea.6 `daa2b1df250d` · ikea.2 `ecffb18dbd7f`
**Portée** : lecture seule, aucun code livré.

---

## § 1 — Events mobility / reliability (par contenu NMF)

Lecture directe des fichiers NMF (`/var/lib/bc4/nmf-source/43e81a34a073/*.nmf`) via `awk -F','`.
Décompte via `nmf_event_light` et présence dans `catalog_release 2.66.2` via `load_catalog_json`.

### 1.1 Events décodés et exposés

| Event | Nom NFF 2.50 | Page | n raw Test_6 | n raw ikea.6 | n raw ikea.2 | n light Test_6 | n light ikea.6 | n light ikea.2 | Décodé | Dans catalog 2.66.2 | n leaves catalog |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **HOA** | Handover/handoff attempt | p.434 | 126 | 0 | 5 | 126 | 0 | 5 | ✓ | **✓** | 27 |
| **HOS** | Handover/handoff success | p.451 | 126 | 0 | 5 | 126 | 0 | 5 | ✓ | **✗ ABSENT** | 0 |
| **HOI** | Handover/handoff information | p.454 | 276 | 0 | 5 | 204 | 0 | 5 | ✓ | **✓** | 3 |
| **RRA** | RRC connection attempt | p.393 | 136 | 5 | 5 | 134 | 5 | 5 | ✓ | ✓ | 2 |
| **RRC** | RRC connection success | p.395 | 135 | 5 | 5 | 134 | 5 | 5 | ✓ | ✓ | 1 |
| **RRD** | RRC connection release | p.397 | 135 | 5 | 5 | 134 | 5 | 5 | ✓ | ✓ | 2 |
| **RRRE** | RRC re-establishment | p.399 | 3 | 0 | 0 | 3 | 0 | 0 | ✓ | ✓ | 2 |
| **RRF** | RRC connection failure | p.396 | 1 | 0 | 0 | 1 | 0 | 0 | ✓ | ✓ | 2 |
| **CREL** | Cell reselection | p.455 | 53 | 1 | 0 | 52 | 1 | 0 | ✓ | ✓ | 20 |
| **PBF** | Packet bearer allocation failure | p.408 | 1 | 0 | 0 | 1 | 0 | 0 | ✓ | **✗ ABSENT** | 0 |
| **LUA** | Location area update attempt | p.475 | 43 | 0 | 0 | 43 | 0 | 0 | ✓ | ✓ | 1 |
| **LUS** | Location area update success | p.476 | 42 | 0 | 0 | 41 | 0 | 0 | ✓ | ✓ | 4 |
| **LUF** | Location area update fail | p.477 | 1 | 0 | 0 | 1 | 0 | 0 | ✓ | ✓ | 3 |
| **TUA** | Tracking area update attempt | p.483 | 46 | 0 | 0 | 45 | 0 | 0 | ✓ | ✓ | 1 |
| **TUS** | Tracking area update success | p.484 | 42 | 0 | 0 | 41 | 0 | 0 | ✓ | ✓ | 4 |
| **TUF** | Tracking area update fail | p.485 | 4 | 0 | 0 | 4 | 0 | 0 | ✓ | ✓ | 1 |
| **SCELLMOD** | Serving cell modification | p.424 | 337 | 5 | 10 | 333 | 4 | 10 | ✓ (REPRISE 9) | ✓ | 63 |

### 1.2 Events absents du corpus NMF

Query vérifié : `awk -F',' '$1==EVENT'` sur les 3 fichiers NMF.

| Code recherché | Signification | Présent dans NMF |
|---|---|---|
| **RLF** | Radio Link Failure (event dédié) | **ABSENT** — ne figure pas dans NFF 2.50 comme event standalone. Le signal "RLF" est capté indirectement via `RRRE` (p.399) ou `RRF` (p.396). |
| **SCGFAIL** / **SCGF** | SCG failure dédié | **ABSENT** — pas d'event standalone. Les SCG failures sont capturées dans `SCELLMOD.result` ∈ {2, 10, 11, 12, 13, 14, 15} (NFF 2.50 p.424 : *Modification result*). |
| **SCGADD** / **SCGMOD** / **SCGREL** | SCG add/mod/release dédiés | **ABSENT** — couverts par `SCELLMOD` groupes `added`/`removed` déjà décodés (REPRISE 9). |
| **RED** / **CELLRE** | Redirection, cell reselection alt-name | ABSENT — cell reselection = `CREL` (p.455) ; redirection NR → cf. `SCELL` NR (p.345-349) handover intra-RAT ou `HOA` inter-RAT. |

### 1.3 Lacunes catalogue 2.66.2 (events décodés mais pas exposés)

- **HOS** (Handover success) : 126 records décodés sur Test_6 + 5 sur ikea.2, mais **0 leaf** dans le catalogue. Fichier:ligne : `app/kpi/catalog_release/catalog_2.66.2.json` — pas de node `ev_hos`. Les champs (sans doute `hos_*`) sont dans `nmf_event_light` mais non exposés comme feuilles.
- **PBF** (Packet bearer failure) : 1 record décodé sur Test_6, mais **0 leaf**. Fichier:ligne idem.

**Les 2 events sont décodés** par le décodeur (`nmf_event_light` contient leurs rows), mais **absents de la tree hiérarchie**. Pour les KPI mobilité, HOS est critique (dénominateur du taux de succès HO).

---

## § 2 — Événements SCG failure dans SCELLMOD (vérifié)

NFF 2.50 p.424 : `SCELLMOD.result` encode l'issue de la modification SCG :

```
1  = Succeeded
2  = Failed (générique, SCGFailureInformation non transmis dans timeout 11 s)
10 = Timer expiry        (SCGFailureInformation)
11 = Random access problem
12 = RLC max retransmissions
13 = Sync reconfiguration failure SCG
14 = SCG reconfiguration failure
15 = SRB3 integrity failure
```

Live counts par capture :

```sql
SELECT capture_id, scellmod_result, COUNT(*)
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='SCELLMOD'
GROUP BY capture_id, scellmod_result ORDER BY capture_id, scellmod_result;
```

Résultat (query live vérifié) :
```
Test_6  : result=1  333  (100 % succès, 0 failure)
ikea.6  : result=1    4  (100 % succès, 0 failure)
ikea.2  : result=1   10  (100 % succès, 0 failure)
```

**Observation importante** : sur les 3 captures Test_6, **aucune failure SCG** décodée. Le KPI SCG failure rate serait donc 0 % sur ce corpus (nécessite une capture de test avec échecs réels pour valider la formule).

---

## § 3 — KPI mobilité proposés (sans implémentation)

Toutes les formules utilisent l'ordre `(capture_id, seq)`, jamais `ts`.

### 3.1 Taux de succès HO (intra-fréquence LTE)
```
HO_SUCCESS_RATE = COUNT(HOS) / NULLIF(COUNT(HOA), 0)
   events sources : HOA (p.434), HOS (p.451)
   Test_6 : 126 / 126 = 100 %  ·  ikea.6 : 0 / 0 (N/A)  ·  ikea.2 : 5 / 5 = 100 %
```
→ Nécessite HOS **exposé au catalogue** (actuellement absent).

### 3.2 Nombre de RLF (approximé par RRRE)
```
RLF_COUNT ≈ COUNT(RRRE) + COUNT(RRF)
   events sources : RRRE (p.399), RRF (p.396)
   Test_6 : 3 + 1 = 4  ·  ikea.6 : 0  ·  ikea.2 : 0
```
→ RLF n'est pas un event standalone NFF 2.50. L'approximation standard est : `RRRE` déclenchée post-RLF, plus `RRF` sur failure RRC connection. À documenter clairement comme **approximation**.

### 3.3 Durée moyenne du handover
```
HO_MEAN_DURATION_MS = AVG(hoi_ho_duration)
   event source : HOI (p.454) champ `hoi_ho_duration`
```
→ HOI déjà exposé (3 leaves).

### 3.4 Taux de SCG failure
```
SCG_FAIL_RATE = COUNT(SCELLMOD.result IN (2,10,11,12,13,14,15)) / NULLIF(COUNT(SCELLMOD), 0)
   event source : SCELLMOD.result (p.424)
```
→ SCELLMOD déjà exposé (63 leaves).

### 3.5 Taux de succès location/tracking area update
```
LAU_SUCCESS_RATE = COUNT(LUS) / NULLIF(COUNT(LUA), 0)   -- LTE Idle re-sel
TAU_SUCCESS_RATE = COUNT(TUS) / NULLIF(COUNT(TUA), 0)   -- LTE EMM
   events : LUA/LUS/LUF (p.475-477), TUA/TUS/TUF (p.483-485)
   Test_6 : LAU 42/43 = 97.7 %, TAU 42/46 = 91.3 %
```
→ Tous présents + exposés.

### 3.6 Taux de cell reselection
```
CELL_RESEL_COUNT = COUNT(CREL)
CELL_RESEL_RATE_PER_MIN = COUNT(CREL) / (capture_duration_min)
   event source : CREL (p.455)
   Test_6 : 52 CREL  ·  ikea.6 : 1  ·  ikea.2 : 0
```
→ CREL exposé (20 leaves).

### 3.7 Taux d'échec RRC connection
```
RRC_FAIL_RATE = COUNT(RRF) / NULLIF(COUNT(RRA), 0)
RRC_RELEASE_DROP_RATE = COUNT(RRD WHERE drop) / NULLIF(COUNT(RRC), 0)
   events sources : RRA (p.393), RRC (p.395), RRD (p.397), RRF (p.396)
   Test_6 : RRF 1 / RRA 136 = 0.74 %
```
→ Tous présents.

### 3.8 Interruption HO (hole dans la série throughput)
```
HO_INTERRUPTION_MS ≈ gap entre `HOA.seq_last` et `HOS.seq` dans l'ordre
                    (capture_id, seq) ; mesurable sur throughput PHRATE
```
→ Approximation : nécessite `HOA.seq` + `HOS.seq` + PHRATE sampled rate. **Pas d'event explicite "HO interruption" en NFF 2.50**.

---

## § LIVRABLE / recommandations avant implémentation

1. **Combler les 2 absences catalogue** (HOS p.451, PBF p.408) comme condition préalable pour les KPI § 3.1 et § 3.4.
2. **Ne pas confondre RLF ↔ RRRE** : le KPI RLF est une approximation (document explicite au ux).
3. **SCG failure codes** : exposer un breakdown de `scellmod_result` (groupé par 1=succès, 2=failed générique, 10-15=cause spécifique) côté catalogue.
4. **Captures de référence** : seule Test_6 porte des HO (126/126) et des RRRE (3) ; ikea.6/ikea.2 n'ont pas de HO. Pour valider les KPI à l'échelle, prévoir une capture de test avec > 100 HO + > 10 RLF.

En attente de validation user avant implémentation.

— Agent BC5
