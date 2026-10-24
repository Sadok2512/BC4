# HANDOFF — decoder 1.6.0 / catalog 2.50

Fichier de passation entre sessions BC3. Une session neuve doit pouvoir
reprendre en lisant **ce fichier seul**.

Dernière mise à jour : 2026-10-24 18:00Z (session Opus 4.7 1M, 3e passe).

**ÉTAT 2.2a : YAMLs 2.50 validés (85/87 LTE common events alignés). Keysight uploadé.
Decoder refactor pas encore commité (prochaine fenêtre).**

## Progrès 3e passe

- B1 levé : `/home/devmat/BC4/specs/Nemo_FileFormat.zip` déposé (108 MB,
  2 .nmfs échantillons + PDF spec).
- B2 appliqué dans `build_yamls.py` : filtre section par systems (7/8→LTE,
  9→NR, LTE and NR→les deux) + context_count carry-over + formula col
  unifiée.
- Diff validation : 85/87 LTE common events MÊMES cols vs 1.5.1. Les 2
  outliers (CREL, HOA) ont des layouts conditionnels → 2.2b.
- 77 events gagnent des champs nouveaux 2.50 (#BF.bts_file, #DL.device_label,
  #HW+4, #LICENSE+5, etc.).

## Reste à faire 2.2a (prochaine fenêtre)

1. Decoder lit schemas-2.50/ : patcher `app/nmf_decoder/schema.py` fonction
   `schemas()` pour charger depuis `schemas-2.50/` avec fallback sur
   `schemas/` pour CREL/HOA + les 4 events only_in_old (#EI, #SI, HOS, SIPREGC).
2. Projet TEST **NFF_SAMPLE** → ingest `/tmp/keysight/Nemo_FileFormat/
   File_Format_2.50_Sample_datas/OD_921_drive_train_22Jun30 091813.{1,2}.nmfs`.
   Note : extension `.nmfs` streaming — vérifier que source.py accepte.
3. Projet TEST **TEST_1_6** → re-ingest capture témoin 44621571bccc depuis
   un .nmf de son projet d'origine.
4. Gardes sur ces 3 captures : G29 ×3 = 0 écart, G26 = 0 décalage, G28 plages.
5. Si tous verts : pg_dump + re-decode 94+2 nohup.

## BLOCKERS DÉCOUVERTS (2.2a, 2e passe)

### B1 — Keysight .nmf absents du filesystem

```
ls /home/devmat/BC4/specs/*.zip
  BC4_SPECS_ALL.zip         ← pas de .nmf dedans
  bc4_dict_v2_specs*.zip    ← pas de .nmf
  nff_2.50_pack.zip         ← CSV + TXT + PDF uniquement
  nmf_full_catalogue_2.19.zip ← CSV uniquement
```

**Aucun `Nemo_FileFormat.zip`** sur le filesystem. L'oracle Keysight G29=0 est
impossible tant que ce fichier n'est pas livré. Action requise : upload du
zip Keysight OU chemin corrigé.

### B2 — field_no CSV NFF 2.50 est SECTION-RELATIF

Révélation critique en comparant avec 1.5.1 :

```
CSV 2.50 : CI, Parameters,          1, Measured system
CSV 2.50 : CI, Parameters for GSM,  1, C/I                 ← field_no=1 GSM
CSV 2.50 : CI, Parameters for LTE,  1, #Header params      ← field_no=1 LTE
CSV 2.50 : CI, Parameters for LTE,  3, Cell type           ← field_no=3 LTE
```

Mon générateur Phase 2.1 agrégeait tous les sections → collisions col
(`col=5` 3× pour mêmes field_no de sections différentes).

**Correction attendue** :
```
col_absolu = system_col(event) + field_no_SECTION_matching_systems
```

Donc `ci.cell_type` LTE : system_col=4 + field_no_LTE=3 = **col 7** (=
1.5.1 existant, pas 3). Le "diff" apparent `ci.cell_type 7→3` était un
artefact de ma méthode, pas un vrai décalage de la spec.

**Conséquence majeure** : la 1.5.1 était correcte sur les technos actives
(LTE). La dette G26 que BC3 cite est **beaucoup moins étendue** qu'il ne
semblait. À confirmer sur chaque event une fois le filtre section-par-system
implémenté.

### B3 — Scope du refactor réduit

Vu B2, le refactor "lire YAML 2.50" perd 90% de son intérêt pour les events
LTE déjà bien décodés par 1.5.1. Le vrai gain 2.50 est :
- Les 193 events ADDED (UMTS legacy + NR advanced + #metadata) jamais
  décodés avant.
- La couverture NR explicite (cell_scoped=true pour les events avec `Scope`
  champ dans le CSV).
- Les nouveaux champs ajoutés aux 85 events communs (#HW +4 champs,
  #LICENSE +5, etc.).

## NEXT SESSION — reprise 2.2a (après upload Keysight)

1. **Patch `scripts/catalog/build_yamls.py`** : filtre CSV par section
   matching les `systems: [N]` de l'event (section_to_system map à construire).
   Validation : diff vs schemas/ sur les 87 common events doit montrer
   0 move pour les sections LTE actives (sinon vraie dette G26).
2. **Après upload** `/home/devmat/BC4/specs/Nemo_FileFormat.zip` :
   ingérer 2 .nmf → projet NFF_SAMPLE, decode avec decoder actuel (1.5.1)
   d'abord → ligne de base G29 ×1.
3. **Decoder 1.6.0** : lire YAMLs 2.50 pour les 193 ADDED events + nouveaux
   champs des 85 communs, le reste reste 1.5.1. Fallback paresseux.
4. **Projet TEST_1_6** : décoder 44621571bccc. G29/G26/G28 sur ce seul capture.
5. Si tout vert : pg_dump + re-decode 94+2 nohup.

## Build 2.50.3 — toujours current (inchangé 2.2a)

- `catalog_release.version = 2.50.3  sha=556be8e9...  is_current=TRUE`
- `n_leaves_displayed = 5710`  (contrat G18b)
- GC1 PASS.

---

## Branche de travail

```
feat/bc3-catalog-2.50   (bc4-back + franco-focus-forge)
Base   : main
Commits : 4 commits BC3 posés
  2778922 Phase 2 preamble — build 2.50.3 (Capture context dedupe + Other tech + n_displayed=5710)
  <sha4>  Phase 2.1 — generate 282 YAMLs 2.50 + diff vs schemas 1.5.1
  <sha3>  Phase 1 bis — categories.yaml + corpus coverage → catalog 2.50.2
  <sha2>  Phase 1 — build_catalog.py → catalog_2.50.1.json (first build)
  <sha1>  Phase 0 — catalog versioning scaffolding (NFF 2.50)
```

## Objectif global

Catalogue versionné (NFF 2.50) + decoder 1.6.0 compatible, remplaçant la
dette 1.5.1 (colonnes décalées, 193 events jamais décodés).

Spec source unique : `/home/devmat/BC4/specs/nff_2.50_pack.zip`
  → `nmf_all_events_fields_2.50.csv` (282 events, 4 393 champs)
  → `nemo_file_format_2.50.txt` (enums : cell types, bands, causes)

Oracle Keysight (pour G29=0 preuve) : `/home/devmat/BC4/specs/Nemo_FileFormat.zip`
(contient 2 .nmfs — à décompresser et ingérer dans projet TEST `NFF_SAMPLE`).

## Phase 0 — FAIT ✅

- `alembic 0048_catalog_release.py` : table `catalog_release(version PK, spec_version,
  decoder_min_version, sha256, n_categories, n_metrics, n_leaves, is_current)`.
  Partial unique index : au plus 1 ligne `is_current=TRUE`.
- `app/models/base.py` : classe `CatalogRelease`.
- `app/kpi/catalog_release/` : package avec `registry.py` (`current_catalog(db)`,
  `sha256_file(path)`). Renommé pour éviter collision avec `app.kpi.catalog`.
- `scripts/guards_2026_10/GC1_catalog_sha.py` : garde sha DB ↔ fichier.
- `CHANGELOG_CATALOG.md` : règle de bump + versions.
- Migration appliquée : `alembic_version=0048_catalog_release`.

## Phase 1 bis — FAIT ✅ (catalog 2.50.3)

Artefacts :
```
app/kpi/catalog_release/catalog_2.50.1.json    (premier build naïf, obsolète)
app/kpi/catalog_release/catalog_2.50.2.json    (hiérarchie v10, 19 cat, Unclassified)
app/kpi/catalog_release/catalog_2.50.3.json    <-- COURANT (is_current=TRUE)
scripts/catalog/build_catalog.py               (CSV + categories.yaml + enums + corpus → JSON)
scripts/catalog/categories.yaml                (141 events mappés + default→Other)
```

Build 2.50.3 (chiffres contrat) :
```
tech=4 (LTE/NR/Shared/Other)  categories=19  events_kept=280
classified=150 unclassified=140→Other  excluded=2 (identité #EI/#SI)
n_metrics_bare=3419  leaves_cell=24996  n_leaves_total=28415
n_leaves_displayed=5710   <-- CONTRAT G18b
sha256=556be8e9cf546416f884d5db6011c07620cbc2e2bb2781d0481f5102960e9ced
```

Enums parsés :
- cell_type_lte_scell (1817), cell_type_lte_mesure (5),
  cell_type_nr (68), band_lte (77).

Garde GC1 = **PASS**.

## Phase 2.1 — FAIT ✅ (YAMLs générés + diff collé)

- `scripts/catalog/build_yamls.py` : CSV → 280 YAMLs dans
  `app/nmf_decoder/schemas-2.50/` (`_hash_X.yaml` pour les events `#X`).
- Diff collé : `exports/diff_yamls_phase2.txt`
```
old(v1.5.1)=91  new(2.50)=280
only_in_old : 4 (#EI,#SI,HOS,SIPREGC)
only_in_new : 193 (ADDED — nombreux UMTS/CDMA, NR advanced, # metadata)
common      : 87
added_fields: 85 events
removed_fields: 73 (renommages préfixe event.* — pas vraiment removals)
moved cols  : 42 events (confirmation dette G26)
```

## Phase 2.2 — À FAIRE (découpage BC3)

Scope : **113 events du corpus** (requête `SELECT DISTINCT event_code FROM
nmf_event_light` à faire pour liste exacte) + events des 2 .nmfs Keysight.
Les 167 autres YAMLs restent dans le dépôt, chargés paresseusement si un
fichier les contient un jour (unk_ sinon). Pas de refactor pour technos
absentes.

### 2.2a (prochaine session) — Decoder lit YAML 2.50 + tests isolés

Livrable : light.py / deep.py / source.py (`app/nmf_decoder/`) chargent les
YAMLs 2.50 (offsets corrects, discriminateurs cell_type, agg par champ)
et décodent :
  - les 2 .nmfs Keysight → projet TEST **NFF_SAMPLE** (à créer)
  - la capture témoin **44621571bccc** dans un projet **TEST_1_6** (à créer)

Gardes à exécuter sur ces 3 captures (G29 ×3, G26=0, G28 plages) :
```
docker exec -w /app bc4-api-1 sh scripts/guards_2026_10/run_all.sh
```

G29 doit être à **ZÉRO écart** sur l'oracle Keysight (preuve que 1.6.0
lit la 2.50 comme Keysight l'écrit). Si un garde échoue → corrige avant
de toucher au corpus.

**Ne pas** re-décoder les 94 captures à cette étape.

### 2.2b — GPS/CQI/signalling en Light

- GPS Quality / HDOP / Satellites exposés (fix_quality=0 → `stale_fix`
  jamais `exact`).
- CQI pondéré par Sample duration (agg=`mean_weighted` dans YAML).
- rrcsm / l3sm en Light (actuellement vides sur certaines captures).

### 2.2c — Re-decode 94 + 2 nohup

1. **pg_dump explicite** avant le re-decode (le cron 02:00 ne suffit pas
   si on lance avant). SHA collé.
   ```
   /home/devmat/BC4/scripts/pg_dump_daily.sh
   sha256sum /home/devmat/BC4/exports/bc4_$(date +%F)*.dump
   ```
2. Script re-decode script (reuse `app/services/import_worker.py` logic)
   lancé en nohup, log `exports/redecode_94_<ts>.log`, PID collé.
3. Rapport matin :
   ```sql
   SELECT decoder_version, COUNT(*) FROM nmf_capture GROUP BY decoder_version;
   ```
   Doit montrer combien de captures en 1.6.0 vs 1.5.1 restantes (échec
   mid-route laisse corpus mixte — c'est accepté par BC3).
4. Gardes complets : G20, G29 ×3, G24, G25, G26, G27, G28, G18b, GPS_stale.

### Après 2.2c → Phase 3

- `/metrics` et `/metrics/table` renvoient `catalog_version` + `decoder_version`
  dans l'enveloppe.
- Front affiche "Catalog 2.50.3 · Decoder 1.6.0" au pied du panneau Metrics.
- Front : arbre généré depuis /metrics (jamais local), Technology niveau 1.
- Colonne **Task** (CMDREQ/CMDCOMP par seq), fiche Info capture (SCRIPT,
  DAA/DREQ/DCOMP).

## Dette actée par le diff Phase 2.1

Catalog 2.50.3 pointe vers des champs que Light n'a pas encore (colonnes
déplacées en 1.5.1 ou events jamais décodés). **D'ici 2.2c**, `/metrics`
doit servir `reason='redecode_required'` sur ces feuilles — PAS des
valeurs fausses.

Colonnes déplacées confirmées :
```
ci.cell_type              col 7 → 3
cqi.wb_cqi_1              col 9 → 5
cqi.wb_pmi                col 12 → 8
daa.application_protocol  col 4 → 1
crel.* (10 champs)
```

À patcher dans `app/routes/metrics.py` route catalog : pour chaque leaf
du catalogue 2.50.3, si `leaf.event in events_in_corpus_decoded_1.5.1`
ET `leaf.col ≠ col_1.5.1`, émettre `reason='redecode_required'`.

## DEPLOY_LOCK

**Statut à la fin de cette session : LIBÉRÉ**.

Reprendre uniquement pour fenêtres rebuild/re-decode avec holder+raison
explicites dans `/home/devmat/BC4/DEPLOY_LOCK`.

## Commandes de reprise

```bash
# 1) Vérifier branche + lock
cd /home/devmat/BC4/bc4-back && git status
cat /home/devmat/BC4/DEPLOY_LOCK      # doit être libre (holder: vide)

# 2) Vérifier catalog_release courant
docker exec bc4-db-1 psql -U bc4 -d bc4 -c "SELECT version, sha256, is_current FROM catalog_release"
# Attendu : 2.50.3  556be8e9…  t

# 3) Vérifier migrations
docker exec bc4-db-1 psql -U bc4 -d bc4 -tAc "SELECT version_num FROM alembic_version"
# Attendu : 0048_catalog_release

# 4) Garde GC1
docker exec -w /app bc4-api-1 python scripts/guards_2026_10/GC1_catalog_sha.py
# Attendu : GC1_VERDICT PASS

# 5) Lister 113 events corpus (pour scope 2.2a)
docker exec bc4-db-1 psql -U bc4 -d bc4 -tAc \
  "SELECT DISTINCT event_code FROM nmf_event_light ORDER BY event_code" | wc -l

# 6) Décompresser Keysight (si pas fait)
python3 -c "import zipfile; zipfile.ZipFile('/home/devmat/BC4/specs/Nemo_FileFormat.zip').extractall('/tmp/keysight')"
ls /tmp/keysight/*.nmf
```

## PIDs / logs en cours

Aucun process BC3 actif à la fin de cette session.
Fichiers log récents :
```
/home/devmat/BC4/exports/diff_yamls_phase2.txt   (diff YAMLs collé)
/home/devmat/BC4/exports/guards_2026_10_output_20261024_145344.txt  (gardes réécrits sortie)
```

## Guards — dernier résultat (2026-10-24 ~15:00Z, pré-Phase 2)

| Guard | Verdict | Note |
|---|---|---|
| GC1_catalog_sha | PASS | sha DB=disk pour catalog 2.50.3 |
| G29_file_vs_db  | tableaux livrés | pas de verdict explicite — données en output |
| G26_offsets     | FAIL partiel | 33/91 aligned, 50 "?" (bugs dans ma détection) |
| G27_unk         | FAIL | 99 events, 32M lignes, 8743 champs non alloués |
| G28_ranges      | tableaux livrés | P1/P50/P99 pour toutes métriques × 3 captures |
| G24_leaves      | FAIL | faux-zéros détectés |
| G25_catalogue   | FAIL | 952 orphans (fix attendu après 2.2c + /metrics refactor) |
| G18b_parity     | PASS | cache = fresh |
| GPS_stale       | PASS | 0 anomalie, scanner d8d7fa995c44 témoin OK |

Attendus post-2.2c : G26=0, G27 ≤ 10%, G25=0, G24 propre.
