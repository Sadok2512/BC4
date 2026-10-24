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

(aucune version publiée — scaffolding Phase 0 posé 2026-10-24)
