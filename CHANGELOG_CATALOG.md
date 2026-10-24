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

## Versions

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
