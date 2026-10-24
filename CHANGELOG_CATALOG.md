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
