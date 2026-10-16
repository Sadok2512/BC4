"""Enrichissement `measurement_points` depuis `bc4-decoder 2.0.0` (0.30.0).

Module séparé pour exploiter `decode_nmf_file_full(path)` qui expose
`meta` + events catégorisés avec `raw_fields` nommés. Complémentaire à
`app/services/populate_measurements.py` (skeleton depuis
`stg_measurement_raw`) : ce module ENRICHIT en place les lignes de
mesure (métriques CELLMEAS prouvées + `operator_source`, `service_*`,
`phase`, `env`, `rat`, `earfcn`) sans créer de doublons.

Doctrine (jamais déviée) :
- Par le CONTENU, jamais par l'étiquette.
- Ordre canonique `(capture_id, seq)` strict — service action et GPS se
  rattachent au DERNIER marqueur précédent dans cet ordre, pas par `ts`.
- `operator` AUTORITAIRE depuis #DL ; divergence SIB1 déclarée, pas
  masquée.
- Un champ non prouvé = NULL déclaré, jamais inventé.
- Aucune identité abonné en base — la deny-list est déjà appliquée à la
  source par le décodeur.
"""

from app.measure.populate import populate_measurement_points

__all__ = ["populate_measurement_points"]
