# CORRECTION GLOBALE CATALOGUE MÉTRIQUES — Fichier de passation

**Démarrage** : 2026-11-03 (Agent BC5, mode autonome)
**Référence** : `bc4-api-1` + `bc4-front-1` + `bc4-db-1` (stack `bc4_default`, ports 5174/8000/5432) · projet de preuve UNIQUE **Test_6** `43e81a34a073`
**Base version** : décodeur 1.9.0 · catalog_release 2.62.0 · app 1.133.25
**Cible** : décodeur 1.10.x · catalog_release 2.63.0 · app 1.134.0

---

## Point courant

**Position** : étape 0 terminée. Multi-system framework déjà présent dans le décodeur 1.9.0 (`schema_for(event,system)` + `_NR.yaml` → `_variants[9]`, cf `app/nmf_decoder/schema.py:49-53`). **Il reste à ajouter les variants NR manquants + corriger les hard-codes `system==7`**.

**Prochaine étape exacte** : commit `decoder: 1.10.0 — enforce system-aware cell_type + PLAID_NR variant`. Branche main `bc4-back`, HEAD propre à `4df0ac3`.

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
| 1 | décodeur | 1.9.0 → 1.10.0 | *pending* | PLAID NR system=9 projette au moins `plaid_prb_percentage` ou équivalent | *pending* |
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

- **O-01** `app/nmf_decoder/light.py:75` — `if r.event_code=='TXPC' and r.system==7:b['cell_type']=txpc_cell_type(r)` : hard-code `system==7`, `cell_type` jamais set pour NR malgré TXPC_NR.yaml existant. **Fix prévu dans commit décodeur 1.10.0**.
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

**Dernière mise à jour** : 2026-11-03 (étape 0 terminée)
