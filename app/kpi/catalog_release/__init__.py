"""Catalogue versionné NFF 2.50 — scoped sous `app.kpi.catalog_release`
pour ne pas collisionner avec `app.kpi.catalog` (ancien KPI catalog).

- Les artefacts `catalog_<version>.json` sont GÉNÉRÉS par
  `scripts/catalog/build_catalog.py` depuis le CSV spec. Pas d'édition manuelle.
- `app.kpi.catalog_release.registry.current_catalog()` lit la ligne
  is_current de `catalog_release` (table) et retourne (version, sha256, path).
- `/metrics` et `/metrics/table` exposent `catalog_version` + `decoder_version`
  dans l'enveloppe de réponse.
"""
