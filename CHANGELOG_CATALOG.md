# CHANGELOG — Catalogue versionné (NFF 2.50 pack)

Format : `<version> — <date> — ajouté / retiré / renommé, nb feuilles`.

Source unique : `/home/devmat/BC4/specs/nff_2.50_pack.zip`
  → `nmf_all_events_fields_2.50.csv` (282 events, 4 393 champs, 8 colonnes)
  → `nemo_file_format_2.50.txt` (énumérations : cell types, bandes, causes)

Les artefacts `app/kpi/catalog/catalog_<version>.json` sont **générés** par
`scripts/catalog/build_catalog.py` depuis le CSV spec. Aucune édition manuelle.
Chaque build écrit une ligne dans `catalog_release` (sha256, counts) ;
`is_current=TRUE` sur une seule ligne à la fois (contrainte DB).

## Règle de bump

- `spec` change (2.50 → 2.62) = **version mineure** du catalogue.
- Ajout/renommage de feuilles à spec égale = **build**.
- Une feuille **ne disparaît jamais** sans ligne de changelog.
- `metric_id` stable : `<event>.<field_slug>[@<cell_type>]`, dérivé du CSV.
  → Clé partagée /metrics ↔ Light ↔ front. Fin du bug G25 (orphans).

## Définitions

- `n_metrics` = **feuilles hors cellule** (bare leaves) : métriques
  définies par un (event, field) sans discriminator `Cell type`.
- `n_leaves` = total feuilles catalogue = n_metrics (bare) + feuilles
  cellule (créées par cell_type présent dans le corpus + cell_types
  déclarés par la spec mais marqués `displayed=false`).

## Versions

## 2.51.0 — 2026-10-25 — 7 feuilles cellule canoniques @cell_type (Agent BC3)

Phase 2.51.0 lot 1b. Build après redécode des 83 captures UE sous
decoder 1.7.0.

- **7 feuilles cellule canoniques** par event cell-scoped (au lieu
  de 32+ auparavant) : PCell (0), SCell 1 (1), SCell 2 (2), SCell 3 (3),
  SCell 4 (4), PSCell NR (199), SCell NR 100+ (bucket cell_type≥100 hors
  PSCell).
- Chaque feuille porte `cell_type` dimension + colonne. `selectable=false`
  + `reason` si cell_type jamais observé en base (gris côté front).
- Les champs `extra_N` et `*_fil` (MIMOMEAS/CELLMEAS NR) sont posés
  avec `selectable=false` + `reason="FF 2.62 non documenté 2.50 —
  nommage par contenu BC3 2026-10-25"`.
- `decoder_min_version` passé à `1.7.0`.
- Enveloppe `metric_id` étendue avec `cell_label` pour l'affichage front.

Hypothèse enum NR : SCG PSCell=199 (spec NFF 2.50 §Cell type). Les
cell_type NR observés 101/108/117/199 sur 723547b196b3 sont tous dans
le bucket PSCell/SCell NR 100+.


### 2.50.5 — 2026-10-25 — node_id unique par position (préalable Phase 3b)

Correction du contrat `node_id` : 2.50.4 avait 5115 feuilles `displayed=true`
mais seulement **3625 node_ids uniques** (10458 collisions sur l'ensemble des
28718 nodes, dont le pire `lf_dreq_timeout` x28). Cause : le builder
`scripts/catalog/build_catalog.py` dérivait `node_id` de `(event_slug,
field_slug[, cell_type])` sans tenir compte des rangs CSV multiples (NFF 2.50
contient plusieurs sections "Parameters" / "Parameters for LTE" / "Parameters
for NR" avec le même `(event, name)`).

Fix (`scripts/catalog/rebuild_2_50_5_uniqueids.py`, post-processeur du 2.50.4) :
pour chaque `node_id` collisionné, suffixe `_r<i>` où `<i>` est l'ordinal
zero-based de l'occurrence dans l'ordre d'apparition. Première occurrence =
`_r0`, deuxième = `_r1`, etc. (préserve `lf_dreq_timeout_r0..r27`).
L'invariant `len({n.node_id}) == len(nodes)` est VÉRIFIÉ dans le script
(SystemExit si résiduel).

Compte (inchangé vs 2.50.4 — on n'a touché QUE les ids) :
- 4 tech, 19 categories, 280 events_kept
- n_metrics_bare = 3419 ; n_leaves_total = 28 415
- **n_leaves_displayed = 5 115**  (= **5115 node_ids uniques** sur ces feuilles)
- sha256 : `87fb0d13a2cb67276e884298b7d7ba3decc1635d13521024dbaf4610e6cf44a4`

Preuves (post-publication 2.50.5 is_current=TRUE + repopulation cache) :
- G25 strict (sans set()) PASS 15/15 projets : `total_dup_node_ids=0`,
  `total_dup_metric_codes=0`, `total_orphans=0`.
- G18b strict (multiset) PASS 15/15 projets : `dup_cache=0`, `dup_fresh=0`,
  cached==fresh==5115 par projet, divergent=0.
- G24 re-count LIVE sur témoin 134af70a06eb : `candidates_recounted=271`
  colonnes, `false_zeros=0` (plus de "mode trust").

### 2.50.4 — 2026-10-25 — metric_id aligné sur colonnes Light (Phase 3 préambule)

Convention `metric_id` modifiée : `<event_lower>_<field_slug>[@<cell_type>]`
au lieu de `<event>.<field_slug>...` → correspond exactement aux noms de
colonnes `nmf_event_light` (ex. `cellmeas_rsrp`, `ci_rs_snr`, `dci_dci_count`).

Compte :
- 4 tech, 19 categories, 280 events_kept
- n_metrics_bare = 3419 ; n_leaves_total = 28 415
- **n_leaves_displayed = 5 115** (vs 5 710 en 2.50.3 — ajustement
  cell_type coverage corpus post re-decode 1.6.0 : 4 events seulement
  avec `cell_type:N` dimension nommée vs 6 avant)
- sha256 : `cc6c89e4c503e225a5eb5105debb4100162cd696b7077068a20b789b613faa91`

Dette ouverte : `/metrics` endpoint sert toujours le catalogue legacy
(catalog_v3 + catalogue_v6). G25 restera FAIL tant que `/metrics` n'est
pas refactoré pour servir ce JSON 2.50.4.

### 2.50.3 — 2026-10-24 — BC3 Phase 2 feedback

- (a) `Capture context` dédoublonné : toujours `tech=Shared` (plus de
  duplication Shared/LTE).
- (b) Nouvelle Technology **"Other (out of scope)"** (`collapsed_default=
  true` côté UI) ; fallback dans `build_catalog.py` : `default_tech="Other"`,
  `default_category="Legacy UMTS/CDMA/DVB"` depuis `categories.yaml`. Les
  140 events restants (UMTS/HSPA/CDMA/GSM/DVB/WLAN/GAN legacy) y
  atterrissent, repliés, comptés, jamais perdus.
- (c) **`n_leaves_displayed = 5 710`** — chiffre contrat G18b (feuilles
  visibles par l'utilisateur) vs 28 415 total (incluant les feuilles
  cellule spec-déclarées non-présentes dans le corpus → `displayed=false`).
- 9 events `#*` ajoutés à `categories.yaml` (#PRODUCT, #PROJECT, #REPORT,
  #SERVER, #SERVERHW, #SP, #STOP, #UNITID, #VQ) → Capture context Shared.
- Compte final :
    - tech = **4** (LTE, NR, Shared, Other)
    - categories = 19 (17 BC3 + Unclassified + Legacy UMTS/CDMA/DVB)
    - events_kept = 280 ; classified = 150 ; unclassified = 140 (→ Other)
    - excluded = 2 (règle identité : #EI, #SI)
    - n_metrics (bare) = 3 419 ; n_leaves (total) = 28 415 ;
      **n_leaves_displayed = 5 710**
- sha256 : `556be8e9cf546416f884d5db6011c07620cbc2e2bb2781d0481f5102960e9ced`
- GC1 : PASS.

### 2.50.2 — 2026-10-24 — Phase 1 bis (hiérarchie v10 + enums + corpus)

- Hiérarchie imposée par BC3 : Technology (LTE/NR/Shared) → 17 catégories
  → event → (feuilles cellule | feuille bare field). Catégorie
  « Unclassified » visible pour tout event non classé (règle : jamais
  perdu).
- `scripts/catalog/categories.yaml` committed : map event → (tech,
  category, cell_scoped, mask, exclude). 141 events classés.
- 149 events `Unclassified` (visibles, comptés) : `#PRODUCT, #PROJECT,
  #REPORT, #SERVER, #SERVERHW, #SP, #STOP, #UNITID, #VQ, ADJMEAS, AGRANT,
  AMRI, AMRQ, ANRI, APP, AQECHO, AQUL, BEP, BER, CAF, CALLMODI, CARE,
  CELLINFO, CELLLOAD, CELLPOLLUTION, CIPI, CONNECTIONC, CONNECTIOND,
  CRELI, DATE, DCHI, DCHR, DCONTENT, DLALLOCSCAN, DPROFSCAN, DRCI, DSC,
  DSS, DTRACE, DVBBER, DVBFER, DVBI, DVBRATE, DVBRXL, EDCHI, ERR,
  FCHPACKETS, FDRC, FINGER, FREQSCAN, ...` (voir
  `catalog_2.50.2.json → unclassified_events` pour la liste complète).
  La plupart = legacy UMTS/CDMA/DVB hors scope LTE/NR, à classer ou à
  déclarer out-of-scope dans un prochain build.
- 2 events **excluded** (règle identité) : `#EI` (Equipment Identity),
  `#SI` (SIM Identity).
- Enums extraits depuis `nemo_file_format_2.50.txt` :
    - `cell_type_lte_scell` : 1 817 entrées (0..31 + bandes)
    - `cell_type_lte_mesure` : 5 (0=PCell, 1=Listed, 2=Detected, 3=Scanner, 4=Scanner neighbour)
    - `cell_type_nr` : 68 (0=PCell, 1..31=SCell, 100..131=SCG SCell, 199=SCG PSCell, 1000..1002=NR neighbour)
    - `band_lte` : 77 entrées (70001..70240)
- Corpus coverage : 6 events avec `cell_type` observé en nmf_event_light
  (CI, CQI, MACRATE, …) ; feuilles cellule générées pour tous les
  cell_type déclarés par la spec, marquées `displayed=false` pour ceux
  non présents dans le corpus.
- Compte final :
    - tech = 3, categories = 19 (17 BC3 + 1 Unclassified + 1 duplication
      Shared/LTE Capture context à requalifier)
    - events_kept = 280
    - n_metrics (bare leaves) = 3 419
    - n_leaves (total) = **28 415** (3 419 bare + 24 996 cell-scoped)
    - fields excluded (structural / identity / payload / masked index) = 219
- sha256 : `23df8ddc30242524a6a153931ca567627608090d7c30e742d7cf45c73500fdcf`
- Garde GC1 : PASS (sha DB ↔ fichier).

### 2.50.1 — 2026-10-24
- Première génération depuis `nmf_all_events_fields_2.50.csv` (282 events,
  4 393 champs CSV).
- 3 technologies (LTE / NR / Shared), 3 catégories (bucket initial avant
  classification affinée Phase 1 bis), 255 events, **4 055 feuilles**,
  338 champs exclus (structural attributes + identités + payloads).
- decoder_min_version = 1.6.0 (dépendance Phase 2, pas encore shipped).
- sha256 : `26d63b92a25cefc2a45095f0c4515506f6bea3198a348e592c3fa0c90fc044f3`
- Garde GC1 : PASS (sha DB ↔ sha disque).
- Ouvertures : (a) la classification tech / category s'appuie sur des sets
  statiques dans `build_catalog.py` → à remplacer par un parse du
  `nemo_file_format_2.50.txt` (hierarchy + Scope NR). (b) `n_metrics` dans
  `catalog_release` = n_events ici ; la définition correcte pour BC3 est
  « sous-arbre event » — à requalifier au prochain build.
