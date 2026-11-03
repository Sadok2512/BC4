# CORRECTION GLOBALE CATALOGUE MÉTRIQUES — Fichier de passation

**Démarrage** : 2026-11-03 (Agent BC5, mode autonome)
**Référence** : `bc4-api-1` + `bc4-front-1` + `bc4-db-1` (stack `bc4_default`, ports 5174/8000/5432) · projet de preuve UNIQUE **Test_6** `43e81a34a073`
**Base version** : décodeur 1.9.0 · catalog_release 2.62.0 · app 1.133.25
**Cible** : décodeur 1.10.x · catalog_release 2.63.0 · app 1.134.0

---

## Point courant

**Position** : lot 1 schéma PLAID NR **partiel** committé (voir commit 1 ci-dessous). Décodeur bumpé à 1.10.0. Framework multi-system actif (déjà depuis 1.7.0). PLAID NR projette `cell_type` et `scope` mais PAS `rank/prbs/mcs0/mod0/mod1/mcs1` — écart O-A.

**Prochaine étape exacte** :
1. Investiguer O-A (`plaid_rank/prbs/mcs0` à 0 pour système=9) dans `app/nmf_decoder/light.py` : regarder la fonction `read` qui projette les champs. Patch décodeur `1.10.1`.
2. Ensuite PLAIU_NR (schema 2), MACRATE_NR, MACRATEU_NR, DCI (créer LTE+NR), CQI_NR, SCELL_NR, SCELLMOD_NR, CHI_NR — un commit chacun.
3. Après tous les schémas NR : catalog 2.63.0 (lots 3-7), app 1.134.0.
4. Déployer en une seule fois.

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

- **O-A** NEW — `app/nmf_decoder/light.py:read()` ou `effective_col` — PLAID NR projette `cell_type` (dimension) et `scope` (header#2) mais pas `rank/prbs/mcs0/mod0/mod1/mcs1` (col 8-13) alors que les records portent les valeurs. Records :
  ```
  PLAID,17:26:47.787,,9,16,16,199,1,16,1,,0,,45,,0.5,0.13,0.17,1,0.005,0.1,…
  col:                            7 8 9  10 11 12 13 14 15 16   17   18 19 20   21
  ```
  Attendu : plaid_rank=1 (col8), plaid_prbs=16 (col9), plaid_mod0=1 (col10), plaid_mcs0=0 (col12). Observé : tous NULL/0 dans `nmf_event_light`. Investigation à mener : vérifier si `agg: mean` sur `type: int` avec valeur 0 est rejeté (voir `light.py:Stat.add` ligne ~25-33), si `range: [0,8]` filtre, ou si `effective_col` décale les colonnes à cause du context_count NR. Non bloquant pour continuer sur PLAIU_NR etc. mais à boucler avant toute mise en prod.
- **O-01** `app/nmf_decoder/light.py:75` — `if r.event_code=='TXPC' and r.system==7:b['cell_type']=txpc_cell_type(r)` : hard-code `system==7`. **Non prioritaire** car NR cell_type passe par `dimensions(r)` via `dimension: true` dans TXPC_NR.yaml.
- **O-02** `app/nmf_decoder/light.py:82` — `if r.event_code=='CELLMEAS' and r.system==7`: pareil, voisines NR non agrégées. Comment `scope lot ultérieur` déjà noté.
- **O-03** `app/nmf_decoder/schemas/MACRATE.yaml:41` — `code: mac.dl_bler` sans dimension cellule : les 3459 records MACRATE écrivent `mac_dl_bler` avec `cell_type=NULL`, le catalog projette PCell par convention (= chiffre 2530 vu dans la cache). **À corriger dans commit décodeur 1.10.2**.
- **O-04** schema loader `app/nmf_decoder/schema.py:49-53` — `_variants[9]` ok, mais si on veut supporter d'autres systèmes futurs (ex 5=UMTS) il faut généraliser. Pas bloquant.
- **O-05** PLAID NR layout — col5=16 (hdr_n), col7=cell_id (ex 199), reste à cartographier. **À prouver record par record dans commit 1.10.0**.

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
