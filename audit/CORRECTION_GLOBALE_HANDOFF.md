# CORRECTION GLOBALE CATALOGUE MÉTRIQUES — Fichier de passation

**Démarrage** : 2026-11-03 (Agent BC5, mode autonome)
**Référence** : `bc4-api-1` + `bc4-front-1` + `bc4-db-1` (stack `bc4_default`, ports 5174/8000/5432) · projet de preuve UNIQUE **Test_6** `43e81a34a073`
**Base version** : décodeur 1.9.0 · catalog_release 2.62.0 · app 1.133.25
**Cible** : décodeur 1.10.x · catalog_release 2.63.0 · app 1.134.0

---

## Point courant

**Position (REPRISE 2 — 2026-11-03)** : HEAD `853f75d` ; décodeur **1.10.3** live (image `bc4-api:0.124.3-954117d`), 4 schémas NR livrés (PLAID, PLAIU, MACRATE, MACRATEU). O-A **FERMÉ**. Catalog cache 2.62.0 **stale** (updated_at 2026-11-03 03:07, pre-re-decodes).

**Prochaine étape exacte** :
1. Régénérer `metrics_catalog_cache` pour Test_6 → rendre les projections NR visibles.
2. CHI → SCELLMOD → CQI_NR → DCI (LTE+NR) → SCELL NR, un commit + patch + rebuild + deploy chacun.
3. Lots 3-7 : catalog_release 2.63.0, app 1.134.0.

---

## Instances actives

| Nom container | Image | Rôle |
|---|---|---|
| bc4-api-1 | bc4-api:0.123.3-8cb6840 | **API référence** 127.0.0.1:8000 |
| bc4-front-1 | bc4-front-v2:1.133.25-d56cf80 | **Front référence** 5174 |
| bc4-db-1 | postgis/postgis:16-3.4 | **DB référence** 127.0.0.1:5432 |
| bc4-import-worker-1 | bc4-api:0.123.3-8cb6840 | Worker |
| bc4a4-map-legend-* | 1.133.19-2d76694 (DB séparée) | **NE PAS TOUCHER** (debug legend) |

---

## Working tree

`franco-focus-forge` : stash `stash@{0}: parallel-session-map-legend-expand-removal-20261103` (MapMetricDropTarget.tsx + test map-metric-drop.test.tsx) — à restaurer après le dernier commit du chantier.
`bc4-back` : propre.

---

## Table d'avancement par commit

| # | Composant | Version | Commit | Garde (collée dans ce doc §Gardes) | Statut |
|---|---|---|---|---|---|
| 0 | — | — | — | Audit baseline (voir §Baseline mesures) | FAIT |
| 1 | décodeur | 1.9.0 → 1.10.0 | *d75429f* | PLAID NR cell_type=2973 (dont 199=SCG PSCell:2972, 0=PCell:1), scope=2973 ✓ ; rank/prbs/mcs0 encore 0 → O-A | **PARTIEL** |
| 2 | décodeur | 1.10.0 → 1.10.1 | *pending* | PLAIU NR system=9 projette au moins `plaiu_prb_percentage` | *pending* |
| 3 | décodeur | 1.10.1 → 1.10.2 | *pending* | MACRATE NR + fix MACRATE LTE cell_type binding | *pending* |
| 4 | décodeur | 1.10.2 → 1.10.3 | *pending* | MACRATEU NR | *pending* |
| 5 | décodeur | 1.10.3 → 1.10.4 | *pending* | DCI (LTE + NR, YAML à créer) | *pending* |
| 6 | décodeur | 1.10.4 → 1.10.5 | *pending* | CQI NR | *pending* |
| 7 | décodeur | 1.10.5 → 1.10.6 | *pending* | TXPC fix cell_type NR (TXPC_NR existe déjà) | *pending* |
| 8 | décodeur | 1.10.6 → 1.10.7 | *pending* | SCELL NR | *pending* |
| 9 | décodeur | 1.10.7 → 1.10.8 | *pending* | SCELLMOD NR | *pending* |
| 10 | décodeur | 1.10.8 → 1.10.9 | *pending* | CHI NR + LTE_RRC_STATE / NR_RRC_STATE / EMM / état réseau | *pending* |
| 11 | catalog | 2.62.0 → 2.63.0 | *pending* | Lot 3 enum cell_label (SCG SCell N, PSCell, Listed/Detected/Scanner) | *pending* |
| 12 | catalog | 2.63.0 | *pending* | Lot 4 reclassement TUA/TUS/TUF/RRRE/EMM/TAC → LTE>Signalisation, retrait CSI/PMI/MIMOMEAS des voisines | *pending* |
| 13 | catalog | 2.63.0 | *pending* | Lot 5 champ `kind` KPI/KPI_CATEGORICAL/DIMENSION/STRUCT | *pending* |
| 14 | catalog | 2.63.0 | *pending* | Lot 6 fusion `Sample dur./Sample duration` + `display_code` émis par back | *pending* |
| 15 | app | 1.133.25 → 1.134.0 | *pending* | Lot 7 export : colonne par capture + kind/unit/data_type dans l'en-tête | *pending* |
| 16 | deploy | — | *pending* | Pin compose + rebuild + push + CSV régénéré avec header `catalog ≥ 2.63.0` | *pending* |

---

## Baseline mesures (avant tout commit, projet Test_6, catalog 2.62.0)

### B.1 — PLAID par système, par capture
```sql
SELECT capture_id, system, COUNT(*) FROM nmf_event_light
WHERE project_id='43e81a34a073' AND event_code='PLAID'
GROUP BY 1,2 ORDER BY 1,2;
```
```
 a4b0c321c52e | 7 | 14523
 a4b0c321c52e | 9 |  2852
 daa2b1df250d | 7 |  1144
 daa2b1df250d | 9 |    13
 ecffb18dbd7f | 7 |   693
 ecffb18dbd7f | 9 |   107
TOTAL system=9 : 2972 (correction P1 — pas 2852)
```

### B.2 — PLAID colonnes par système (couverture)
```sql
SELECT system,
 COUNT(*) FILTER (WHERE plaid_sample_duration IS NOT NULL) AS sd,
 COUNT(*) FILTER (WHERE plaid_prb_percentage IS NOT NULL)  AS pct,
 COUNT(*) FILTER (WHERE plaid_mcs0 IS NOT NULL)            AS mcs0,
 COUNT(*) FILTER (WHERE plaid_prbs IS NOT NULL)            AS prbs,
 COUNT(*) FILTER (WHERE plaid_dl_tbs_avg IS NOT NULL)      AS tbs
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='PLAID'
GROUP BY 1 ORDER BY 1;
```
```
 7 | 16360 | 13767 | 3243 | 13767 | 3469
 9 |     0 |     0 |    0 |     0 |    0   ← cible lot 1
```

### B.3 — Techno × availability sur le catalog
```
 CAPTURE | available      |   26
 CAPTURE | not_applicable |    1
 LTE     | available      |  237
 LTE     | no_data        | 1072
 LTE     | not_projected  | 5076
 NR      | available      |   26
 NR      | no_data        |   61
 NR      | not_projected  |  327
 Other   | available      |    9
 Other   | no_data        |   73
 Other   | not_projected  | 1348
 Shared  | available      |   34
 Shared  | no_data        |  135
 Shared  | not_projected  |  475
 TOTAL leaves           : 8900
```

### B.4 — Garde final baseline
- bloc étranger sous LTE (`label ~ '\(bloc (UMTS|CDMA|DVB|GSM|NR)'` sous techno=LTE) : **1 967** (attendu 0)
- `cell_label ~ '^SCell\s*(1[0-9]{2}|1[0-9]{3})$'` : **2 400** (attendu 0)
- doublons `metric_id` : **0** ✓
- lignes sans `metric_id` : **0** ✓
- doublons `display_code` : **0 par absence de colonne** (lot 6 → émettre `display_code` dans le back)
- champ `kind` renseigné : **0 / 8900** (lot 5 à faire)

---

## Écarts OUVERTS (fichier:ligne, actionnables)

- **O-01** `app/nmf_decoder/light.py:75` — hard-code `system==7` pour `b['cell_type']=txpc_cell_type(r)`. **Non prioritaire** : NR cell_type passe par `dimensions(r)` via `dimension: true` dans TXPC_NR.yaml.
- **O-02** `app/nmf_decoder/light.py:82` — hard-code `system==7` pour CELLMEAS neighbours. Scope lot ultérieur.
- **O-04** `app/nmf_decoder/schema.py:49-53` — `_variants[9]` ok, mais généralisation à d'autres systèmes (ex 5=UMTS) non implémentée. Pas bloquant.
- **O-A, O-03, O-05 : fermés** — voir commits `4951569` et `d75429f`.

---

## Gardes collées (une par commit)

### Garde pré-commit (baseline décodeur 1.9.0, 2026-11-03)
```sql
SELECT system, COUNT(*) FILTER (WHERE plaid_sample_duration IS NOT NULL),
               COUNT(*) FILTER (WHERE plaid_prb_percentage IS NOT NULL),
               COUNT(*) FILTER (WHERE plaid_mcs0 IS NOT NULL),
               COUNT(*) FILTER (WHERE plaid_prbs IS NOT NULL)
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='PLAID' GROUP BY 1;
```
```
 7 | 16360 | 13767 | 3243 | 13767
 9 |     0 |     0 |    0 |     0  ← cible 1.10.0 : > 0 sur au moins une colonne
```

---

## Protocole de reprise si contexte épuisé

1. Lire ce fichier intégralement (`cat /home/devmat/BC4/bc4-back/audit/CORRECTION_GLOBALE_HANDOFF.md`).
2. `git -C /home/devmat/BC4/bc4-back log --oneline -20` et `git -C /home/devmat/BC4/franco-focus-forge log --oneline -20` pour voir ce qui est commité.
3. Vérifier `git -C /home/devmat/BC4/bc4-back status --porcelain` et `git -C /home/devmat/BC4/franco-focus-forge status --porcelain` : HEAD doit être propre (sinon stash avec nom daté).
4. Reprendre à la ligne "Point courant" ou "Prochaine étape exacte" ci-dessus.
5. Après chaque commit (bc4-back), mettre à jour :
   - La table § Table d'avancement (hash + statut)
   - Le point courant § Point courant
   - La prochaine étape exacte
   - Coller la garde dans § Gardes collées
   - Rebrancher ce fichier au commit via `git add audit/CORRECTION_GLOBALE_HANDOFF.md && git commit --amend --no-edit` OU en commit séparé juste après.

---

## Commit 1 — décodeur 1.10.0, PLAID NR variant (partiel)

**Fichiers** :
- `app/nmf_decoder/__init__.py` : `DECODER_VERSION = '1.10.0'` (bump minor)
- `app/nmf_decoder/schemas/PLAID_NR.yaml` : nouveau, 9 champs header NR (hdr_n, scope, cell_type dim, rank, prbs, mod0, mod1, mcs0, mcs1) — spec NFF 2.50 p.561-563
- `alembic/versions/0085_plaid_nr_scope.py` : add column `plaid_scope` (double precision) sur les 4 tables light/deep/group
- `pyproject.toml` : bump 0.123.3 → 0.124.0
- `CHANGELOG.md` : entrée 0.124.0

**Opérations faites sur bc4-api-1 (live container)** :
1. `docker cp` des 2 fichiers décodeur dans l'image writable layer (schémas et __init__.py)
2. `alembic upgrade head` → migration 0085 appliquée en DB live
3. `decode_capture(force=True)` sur les 3 captures Test_6 (daa2b1df250d 43s, ecffb18dbd7f 45s, a4b0c321c52e 1084s)

**ATTENTION** : les changements sur bc4-api-1 ne survivront pas à un `docker-compose up -d --force-recreate`. L'image réelle `bc4-api:0.123.3-8cb6840` ne contient PAS encore PLAID_NR.yaml. Il FAUT **rebuild l'image en 0.124.0** avant tout re-deploy. **Pas de deploy effectué dans ce commit** — à faire une fois les autres schémas NR + lots 3-7 landés.

**Garde collée (Test_6 complet, 2026-11-03)** :
```sql
SELECT system,
 COUNT(*) FILTER (WHERE plaid_cell_type IS NOT NULL) AS cell_type,
 COUNT(*) FILTER (WHERE plaid_rank IS NOT NULL)      AS rank,
 COUNT(*) FILTER (WHERE plaid_prbs IS NOT NULL)      AS prbs,
 COUNT(*) FILTER (WHERE plaid_mcs0 IS NOT NULL)      AS mcs0,
 COUNT(*) FILTER (WHERE plaid_scope IS NOT NULL)     AS scope
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='PLAID' GROUP BY 1;
```
```
 7 | 16024 | 13767 | 13767 | 3243 |    0   ← LTE inchangé
 9 |  2973 |     0 |     0 |    0 | 2973   ← NR cell_type+scope projetés, autres O-A
```

```sql
SELECT plaid_cell_type, COUNT(*) FROM nmf_event_light
WHERE project_id='43e81a34a073' AND event_code='PLAID' AND system=9 GROUP BY 1 ORDER BY 1;
```
```
 0 |    1   ← PCell NR
 199 | 2972 ← SCG PSCell NR
```

**Prochains schémas à faire (ordre user)** :
1. Corriger O-A sur PLAID (décodeur 1.10.1)
2. PLAIU_NR.yaml (décodeur 1.10.2) — spec NFF 2.50 autour page 570
3. MACRATE : NR variant + fix cell_type dim LTE (`MACRATE.yaml:41` écrit `mac.dl_bler` sans dimension cellule → 3459 records cell_type=NULL)
4. MACRATEU
5. DCI (créer LTE+NR, aucun YAML aujourd'hui)
6. CQI_NR
7. SCELL_NR, SCELLMOD_NR
8. CHI_NR + corriger projection `chi_rrc_state/emm_substate/opmode/serving_system` (actuellement 0 non-null sur Test_6)

**Dernière mise à jour** : 2026-11-03 (lot 1 PLAID NR partiel)

---

## Commit 2 — décodeur 1.10.1, O-A closed (PLAID NR header filter)

**Fichiers** :
- `app/nmf_decoder/store.py:40-80` : `normalize_for_stored_deep` utilise `header_filter` du schéma actif au lieu de `HEADER_SET` global
- `app/nmf_decoder/__init__.py` : `DECODER_VERSION = '1.10.1'`
- `pyproject.toml` + `app/main.py` : back 0.124.0 → 0.124.1
- `CHANGELOG.md`

**Cause O-A localisée** : `app/nmf_decoder/store.py:62-67` (avant patch) — filter sur `HEADER_SET` globale. `HEADER_SET = frozenset(HEADERS)` où `HEADERS = sorted(k for k,v in fields().items() if v['group'] is None)`. Comme `fields()` registre les codes via `setdefault`, LTE wins → `plaid.rank` reste à `group='pla'` même quand il est header en NR → exclu de HEADER_SET → light.add(r) n'agrège jamais → DB NULL.

**Fix** : construire le header filter PAR SCHÉMA ACTIF via `schema_for(record.event_code, record.system).get('header')`. Fallback sur `HEADER_SET` global si le schéma n'a pas de header.

**Garde Test_6 complet (3 captures re-decodées force=True, 2026-11-03)** :
```sql
SELECT system,
 COUNT(*) FILTER (WHERE plaid_cell_type IS NOT NULL) AS cell_type,
 COUNT(*) FILTER (WHERE plaid_rank IS NOT NULL)      AS rank,
 COUNT(*) FILTER (WHERE plaid_prbs IS NOT NULL)      AS prbs,
 COUNT(*) FILTER (WHERE plaid_mcs0 IS NOT NULL)      AS mcs0,
 COUNT(*) FILTER (WHERE plaid_mod0 IS NOT NULL)      AS mod0,
 COUNT(*) FILTER (WHERE plaid_scope IS NOT NULL)     AS scope
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='PLAID' GROUP BY 1;
```
```
 7 | 16024 | 13767 | 13767 | 3243 | 3227 |    0   ← LTE identique au baseline
 9 |  2973 |  1878 |  1878 | 1878 | 1878 | 2973   ← O-A fermé
```

Répartition par cell_type NR :
```
 cell_type |  n   | rank | prbs | mcs0
         0 |    1 |    1 |    1 |    1   ← PCell NR
       199 | 2972 | 1877 | 1877 | 1877   ← SCG PSCell
```

**Garde LTE non régressé** : rank 13767, prbs 13767, mcs0 3243 — identique à la baseline 1.9.0 (pre-chantier).

**Prochain commit** : rebuild image bc4-api 0.124.1-<sha>, pin compose, up -d, puis PLAIU_NR (lot 1 continue).

---

## Commit 3 — décodeur 1.10.2, PLAIU NR variant

**Fichiers** :
- `app/nmf_decoder/schemas/PLAIU_NR.yaml` : nouveau, 13 champs header NR (p.570-572)
- `alembic/versions/0086_plaiu_nr_scope.py` : add `plaiu_scope` double precision sur 4 tables
- `app/nmf_decoder/__init__.py` : `DECODER_VERSION = '1.10.2'`
- `pyproject.toml` + `app/main.py` : back 0.124.1 → 0.124.2

**Garde Test_6 complet, 3 captures re-decodées force=True (2026-11-03)** :
```sql
SELECT system,
 COUNT(*) FILTER (WHERE plaiu_cell_type IS NOT NULL) AS cell_type,
 COUNT(*) FILTER (WHERE plaiu_rank IS NOT NULL)      AS rank,
 COUNT(*) FILTER (WHERE plaiu_prbs IS NOT NULL)      AS prbs,
 COUNT(*) FILTER (WHERE plaiu_mcs0 IS NOT NULL)      AS mcs0,
 COUNT(*) FILTER (WHERE plaiu_mod0 IS NOT NULL)      AS mod0,
 COUNT(*) FILTER (WHERE plaiu_tbs0 IS NOT NULL)      AS tbs0,
 COUNT(*) FILTER (WHERE plaiu_scope IS NOT NULL)     AS scope
FROM nmf_event_light WHERE project_id='43e81a34a073' AND event_code='PLAIU' GROUP BY 1;
```
```
 7 | 10247 | 6998 | 6998 | 2499 | 2506 | 2506 |    0   ← LTE préservé
 9 |  2973 | 1853 | 1853 | 1853 | 1853 | 1853 | 2973   ← NR projeté
```

Lot 1 — schémas NR encore à produire (tous confirmés présents à décoder sur Test_6) :
- MACRATE : 2972 records NR, PDF p.531-536 (NR section p.534). Note : LTE cell_type dim fonctionne déjà via `mac_cell_type` colonne séparée (pas via `cell_type` scalaire — mesure sur Test_6 : PCell=3991, SCell1=4271, SCell2=3784, SCell3=3810, SCell4=168 pour LTE, cf §Baseline). Donc pas de "fix" cell_type à faire — ajouter juste MACRATE_NR.
- MACRATEU : 2972 NR, PDF p.537-540 (NR p.538-540)
- DCI : 4542 LTE + 2972 NR, PDF p.551-554 — **LTE DCI.yaml et NR DCI_NR.yaml à CRÉER tous les deux**
- CQI : 2972 NR, PDF p.575-581 (NR p.579+)
- SCELL : 425 (system=9 only), PDF p.345+
- SCELLMOD : 347 (system NULL — à investiguer), PDF p.424+
- CHI : 654 (system NULL — à investiguer), PDF p.320+ — États RRC/EMM/réseau du Lot 2

**Prochain** : rebuild bc4-api 0.124.2, pin, deploy, puis MACRATE_NR comme décodeur 1.10.3.

---

## Commit 4 — décodeur 1.10.3, MACRATE_NR + MACRATEU_NR

**Fichiers** :
- `app/nmf_decoder/schemas/MACRATE_NR.yaml` : nouveau, 10 champs header (p.534-535)
- `app/nmf_decoder/schemas/MACRATEU_NR.yaml` : nouveau, 10 champs header (p.538-540)
- `alembic/versions/0087_macrate_nr_scope.py` : add `macrate_scope` + `macrateu_scope`
- `app/nmf_decoder/__init__.py` : `DECODER_VERSION = '1.10.3'`
- `pyproject.toml` + `app/main.py` : back 0.124.2 → 0.124.3

**Design choice** : les champs NR MACRATE/MACRATEU sont liés aux colonnes DÉDIÉES
`macrate_*` / `macrateu_*` (qui existent déjà mais étaient vides en LTE). Le LTE
MACRATE écrit sur `mac_dl_*` (colonnes partagées), pas sur `macrate_*`. Donc pas de
collision possible, LTE non régressé.

**Garde Test_6 complet** :
- MACRATE sys=9 (NR) : cell_type=2973, dl_bitrate=2973, dl_bler=2973, dl_new=2973, scope=2973
- MACRATEU sys=9 (NR) : cell_type=2973, ul_bitrate=2973, ul_retr=2973, ul_new=2973, scope=2973
- MACRATE LTE non régressé : mac_dl_bitrate=13767, mac_dl_bler=3459, mac_cell_type=16024

**Note DCI reporté** : les event DCI (LTE+NR) utilisent des groupes à layout variable
(DCI format distribution avec #Variables + Count + ...). Ces groupes nécessitent une
grammaire YAML spéciale (`groups: [...]` avec `layout:variable, count_col, start,
fields` typés — cf PHRATE.yaml / CELLMEAS.yaml pour template). Report au prochain
commit décodeur 1.10.4 ou 1.10.5. Évidence : NFF 2.50 p.551-554 cite 'DCI count /
DCI format / DCI repetitions' sous `#Variables Integer Number of DCI format
distribution variables`. Les records DCI Test_6 ont une largeur variable (nf=16 à 24
pour NR, nf=16 à 19 pour LTE) confirmant les groupes.

**Reste à faire** : DCI (LTE + NR), CQI_NR, SCELL_NR, SCELLMOD_NR, CHI_NR puis lots 3-7.

---

## État au 2026-11-03 — session fin

**Commits livrés cette session (ordre chronologique)** :
| sha | version | ajouté |
|---|---|---|
| 3ced896 | — | handoff initial |
| d75429f | décodeur 1.10.0, back 0.124.0 | PLAID_NR (partiel, O-A ouvert), alembic 0085 plaid_scope |
| 4274516 | — | backfill sha dans handoff |
| d84c7bc | back 0.124.0 (FastAPI sync) | fix app.version |
| dc106d3 | — | pin 0.124.0 |
| 4951569 | décodeur 1.10.1, back 0.124.1 | **O-A closed** (normalize_for_stored_deep per-schema header filter) |
| e1fcac6 | — | pin 0.124.1 |
| cb64e46 | décodeur 1.10.2, back 0.124.2 | PLAIU_NR + alembic 0086 plaiu_scope |
| (pin) | — | pin 0.124.2 |
| 954117d | décodeur 1.10.3, back 0.124.3 | MACRATE_NR + MACRATEU_NR + alembic 0087 macrate/u_scope |
| e00c70f | — | pin 0.124.3 |

**Push effectué** : origin + github pour tous les commits.

**Prod active** : bc4-api:0.124.3-954117d, décodeur 1.10.3, catalog 2.62.0 (inchangé).

**Lot 1 — restant** :
- **CQI_NR** : facile (reuse cqi_rank, cqi_wb_cqi_0 ; migration `cqi_scope` nécessaire). Records nf=19 → 15 data cols, header 5 fields (hdr_n, Scope, Cell type, RI, WB CQI) + 2 groups variables (RI dist, WB CQI dist).
- **SCELL** (NR only, 425 records) : nf=55, PDF p.345+, besoin colonnes dédiées `scell_*` (actuellement 0 colonnes prefixées scell_). Non trivial, besoin plusieurs new columns.
- **SCELLMOD** (system NULL, 347 records) : actuel `systems: any_numeric` + fields vides. PDF p.424 "Parameters for LTE and NR" (bloc partagé). Juste ÉCRIRE le schéma header (14 champs typiques). Reuse `scellmod_*` colonnes existantes.
- **CHI** (system NULL, 654 records) : PDF p.320-323. Contient **RRC state, EMM state, Band, Ch, PCI, Serving system, Operation mode** — **chevauche Lot 2** (états RRC/EMM/réseau). Priorité haute car ferme en partie Lot 2 "0 valeur" côté état.
- **DCI** (LTE+NR, 4542+2972) : groupes à layout variable, besoin grammaire YAML `groups: [{layout:variable, count_col, start, fields:[]}]`. Reporter en lot séparé.

**Lots 2-7 — restant** :
- Lot 3 (enum cell_label) : côté catalog build, à mapper 100+n → SCG SCell n etc. Fichier à trouver dans `app/kpi/metrics_v3.py` ou `app/kpi/catalog_release/*.py`.
- Lot 4 (reclassement TUA/TUS/TUF/RRRE/EMM) : côté catalog classification.
- Lot 5 (champ `kind`) : nouveau champ dans le catalog_release JSON. KPI_CATEGORICAL, DIMENSION, STRUCT, KPI.
- Lot 6 (unicité, display_code émis par back) : refactor front→back pour `display_code`.
- Lot 7 (export : colonne par capture + kind/unit/data_type dans en-tête) : front + back.

**Rebuild/deploy** : à chaque commit décodeur ajouter new column migration = rebuild obligatoire (migration doit s'appliquer à l'image). Pour lots 3-7 (catalog build), rebuild API + éventuellement front selon lot 7.

**Dernière mise à jour** : 2026-11-03 fin de session — décodeur 1.10.3 déployé, 4 schémas NR production + fix O-A.

---

## Commit 5 — décodeur 1.10.4, cell_scoped=true sur variantes NR

**Fichiers** :
- `app/nmf_decoder/schemas/{PLAID,PLAIU,MACRATE,MACRATEU}_NR.yaml` : ajout `"cell_scoped": true`
- `app/nmf_decoder/__init__.py` : `DECODER_VERSION = '1.10.4'`
- `pyproject.toml` + `app/main.py` : back 0.124.3 → 0.124.4

**Cause** (fichier:ligne) : `app/nmf_decoder/cells.py:88` → `if not schema.get('cell_scoped') or b['second']<0:continue`. Les 4 variantes NR livrées en 1.10.0-1.10.3 n'avaient pas `cell_scoped:true` → zéro ligne `nmf_cell_second` pour NR → `dynamic_entries` du catalog (`metrics_catalog_v4.py:1088`) ne surfaçait pas les cellules NR.

**Garde `nmf_cell_second` NR après re-decode daa2b1df250d (cell_index=9670 = _cell_index_for(199,9))** :
```
MACRATE  : macrate_mac_dl_bitrate=13, macrate_mac_dl_bler=13, macrate_scope=13
MACRATEU : macrateu_mac_ul_bitrate=13, macrateu_mac_ul_retr=13
PLAID    : plaid_rank=2, plaid_prbs=2, plaid_mcs0=2, plaid_scope=13
PLAIU    : plaiu_rank=5, plaiu_prbs=5, plaiu_percentage=13
```
