# Catalogue simplifié 2.68.5 — fiches des KPI créés

## LTE_THP_DL_CA_TOTAL

- Source : `nmf_cell_second`, événement `PHRATE`, métrique `pdsch_bitrate`.
- Filtre : système LTE, PCell et SCells documentées, valeur non nulle.
- Unité publiée : `Mbit/s` (`bit/s / 1 000 000`).
- Ordre et clé de calcul : `(capture_id, seq_first)` ; aucun usage de `ts`.
- Implémentation : `app/kpi/metrics_v3.py:589-609`.
- Requête de preuve :

```sql
SELECT capture_id, seq_first AS seq,
       SUM(value) / 1000000.0 AS lte_thp_dl_ca_total_mbit_s
FROM nmf_cell_second
WHERE project_id = :project_id
  AND event_code = 'PHRATE'
  AND metric_code = 'pdsch_bitrate'
  AND value IS NOT NULL
  AND cell_index = ANY(:lte_pcell_and_scell_indices)
GROUP BY capture_id, seq_first
ORDER BY capture_id, seq_first;
```

## LTE_CA_NB_SCELLS

- Source : `nmf_cell_second`, événement `PHRATE`.
- Filtre : système LTE, SCell 1–31 documentées, au moins une valeur PHRATE non nulle.
- Unité publiée : `n`.
- Ordre et clé de calcul : `(capture_id, seq_first)` ; aucun usage de `ts`.
- Implémentation : `app/kpi/metrics_v3.py:610-622`.
- Requête de preuve :

```sql
SELECT capture_id, seq_first AS seq,
       COUNT(DISTINCT cell_index) AS lte_ca_nb_scells
FROM nmf_cell_second
WHERE project_id = :project_id
  AND event_code = 'PHRATE'
  AND value IS NOT NULL
  AND cell_index = ANY(:lte_scell_indices)
GROUP BY capture_id, seq_first
ORDER BY capture_id, seq_first;
```

