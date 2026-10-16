-- 0.33.0 — Preuve chiffrée ``raw_fields → measurement_points.{rsrp,rsrq,
-- sinr,cqi,tx_power,thrpt_dl,thrpt_ul}`` sur un projet (par défaut
-- REF_PETITE_FORET). Exécution :
--
--   psql ... -v project_id="'7e656b8c6c19'" \
--     -f scripts/measurement_mapping_proof.sql
--
-- Doctrine : par le CONTENU jamais par l'étiquette. ``value_converted``
-- de ``param_occurrence`` est en dBm (RRC rsrpResult = index - 141).
-- ``cell0_rsrp_dbm`` est déjà en dBm (nom prouvé bc4-decoder 2.0.0).
-- Preuve ``proven`` si ``|avg(candidate) - avg(rrc)| <= 2 dB``.
--
-- Les lignes du rapport sont imprimées une par une ; les champs
-- ``rejected: no_rrc_reference`` sont volontairement visibles (jamais
-- masqués) pour que la UI/le CHANGELOG puisse les reporter tels quels.

\set ON_ERROR_STOP on
\pset null '—'

\set pid :project_id
\if :{?project_id}
\else
  \set pid '''7e656b8c6c19'''
\endif

\echo
\echo '=== Preuve chiffrée (±2 dB) — projet ' :pid ' ==='
\echo

-- ---------------------------------------------------------------------
-- RSRP : cell0_rsrp_dbm (CELLMEAS) vs measResultPCell/rsrpResult (RRC)
-- ---------------------------------------------------------------------
WITH cand AS (
  SELECT (raw_fields ->> 'cell0_rsrp_dbm')::double precision AS v
  FROM stg_event_raw
  WHERE project_id = :pid AND category = 'cellmeas'
    AND raw_fields ->> 'cell0_rsrp_dbm' IS NOT NULL
), rrc AS (
  SELECT CAST(value_converted AS double precision) AS v
  FROM param_occurrence
  WHERE project_id = :pid
    AND path ~ 'measResultPCell/rsrpResult$'
    AND value_converted IS NOT NULL
)
SELECT 'rsrp' AS metric,
       'cell0_rsrp_dbm' AS candidate_field,
       'measResultPCell/rsrpResult$' AS rrc_path,
       (SELECT COUNT(*) FROM cand) AS n_candidate,
       (SELECT COUNT(*) FROM rrc) AS n_rrc,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM cand) AS avg_candidate,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM rrc)  AS avg_rrc,
       (SELECT ROUND(((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc))::numeric, 2)) AS delta_avg_db,
       CASE
         WHEN (SELECT COUNT(*) FROM cand) = 0 THEN 'rejected: no_candidate_sample'
         WHEN (SELECT COUNT(*) FROM rrc)  = 0 THEN 'rejected: no_rrc_sample'
         WHEN ABS((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc)) <= 2.0 THEN 'proven'
         ELSE 'rejected: delta_out_of_tolerance'
       END AS verdict;

-- ---------------------------------------------------------------------
-- RSRQ : cell0_rsrq_db (CELLMEAS) vs measResultPCell/rsrqResult (RRC)
-- ---------------------------------------------------------------------
WITH cand AS (
  SELECT (raw_fields ->> 'cell0_rsrq_db')::double precision AS v
  FROM stg_event_raw
  WHERE project_id = :pid AND category = 'cellmeas'
    AND raw_fields ->> 'cell0_rsrq_db' IS NOT NULL
), rrc AS (
  SELECT CAST(value_converted AS double precision) AS v
  FROM param_occurrence
  WHERE project_id = :pid
    AND path ~ 'measResultPCell/rsrqResult$'
    AND value_converted IS NOT NULL
)
SELECT 'rsrq' AS metric,
       'cell0_rsrq_db' AS candidate_field,
       'measResultPCell/rsrqResult$' AS rrc_path,
       (SELECT COUNT(*) FROM cand) AS n_candidate,
       (SELECT COUNT(*) FROM rrc) AS n_rrc,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM cand) AS avg_candidate,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM rrc)  AS avg_rrc,
       (SELECT ROUND(((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc))::numeric, 2)) AS delta_avg_db,
       CASE
         WHEN (SELECT COUNT(*) FROM cand) = 0 THEN 'rejected: no_candidate_sample'
         WHEN (SELECT COUNT(*) FROM rrc)  = 0 THEN 'rejected: no_rrc_sample'
         WHEN ABS((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc)) <= 2.0 THEN 'proven'
         ELSE 'rejected: delta_out_of_tolerance'
       END AS verdict;

-- ---------------------------------------------------------------------
-- SINR : pas de référence RRC chiffrée canonique en LTE Rel-8.
-- ``rs-sinr-r13`` existe LTE-A mais n'est pas peuplé sur le corpus
-- Petite-Forêt → rejected: no_rrc_reference (déclaré, pas masqué).
-- ---------------------------------------------------------------------
WITH cand AS (
  SELECT (raw_fields ->> 'cell0_sinr_db')::double precision AS v
  FROM stg_event_raw
  WHERE project_id = :pid AND category = 'cellmeas'
    AND raw_fields ->> 'cell0_sinr_db' IS NOT NULL
), rrc AS (
  SELECT CAST(value_converted AS double precision) AS v
  FROM param_occurrence
  WHERE project_id = :pid
    AND path ~ 'rs-sinr-r13$'
    AND value_converted IS NOT NULL
)
SELECT 'sinr' AS metric,
       'cell0_sinr_db' AS candidate_field,
       'rs-sinr-r13$ (LTE-A, souvent absent)' AS rrc_path,
       (SELECT COUNT(*) FROM cand) AS n_candidate,
       (SELECT COUNT(*) FROM rrc) AS n_rrc,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM cand) AS avg_candidate,
       (SELECT ROUND(AVG(v)::numeric, 2) FROM rrc)  AS avg_rrc,
       (SELECT ROUND(((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc))::numeric, 2)) AS delta_avg_db,
       CASE
         WHEN (SELECT COUNT(*) FROM cand) = 0 THEN 'rejected: no_candidate_sample'
         WHEN (SELECT COUNT(*) FROM rrc)  = 0 THEN 'rejected: no_rrc_reference'
         WHEN ABS((SELECT AVG(v) FROM cand) - (SELECT AVG(v) FROM rrc)) <= 2.0 THEN 'proven'
         ELSE 'rejected: delta_out_of_tolerance'
       END AS verdict;

-- ---------------------------------------------------------------------
-- CQI / TX_POWER / THRPT_* : pas de référence RRC chiffrée partagée.
-- Déclarés ouverts (NULL à l'aval), le mapping reste rejected tant
-- qu'une référence externe n'est pas câblée (iPerf GT, etc.).
-- ---------------------------------------------------------------------
SELECT 'cqi'      AS metric, 'rejected: no_rrc_reference' AS verdict
UNION ALL SELECT 'tx_power', 'rejected: no_rrc_reference'
UNION ALL SELECT 'thrpt_dl', 'rejected: no_rrc_reference'
UNION ALL SELECT 'thrpt_ul', 'rejected: no_rrc_reference';
