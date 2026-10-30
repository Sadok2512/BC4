\set ON_ERROR_STOP on
BEGIN READ ONLY;
WITH identities AS (
  SELECT DISTINCT
    CASE
      WHEN cell_arfcn BETWEEN 0 AND 599 THEN 2100
      WHEN cell_arfcn BETWEEN 1200 AND 1949 THEN 1800
      WHEN cell_arfcn BETWEEN 2750 AND 3449 THEN 2600
      WHEN cell_arfcn BETWEEN 3450 AND 3799 THEN 900
      WHEN cell_arfcn BETWEEN 6150 AND 6449 THEN 800
      WHEN cell_arfcn BETWEEN 9210 AND 9659 THEN 700
    END AS reference_channel,
    cell_pci
  FROM nmf_cell_identity
  WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e'
    AND system=7 AND cell_type IN (1,2)
), candidate_counts AS (
  SELECT i.reference_channel,i.cell_pci,count(r.id) AS candidates
  FROM identities i
  LEFT JOIN cell_ref r
    ON upper(r.techno)='4G' AND r.earfcn=i.reference_channel
   AND r.pci=i.cell_pci AND r.geom IS NOT NULL
  GROUP BY i.reference_channel,i.cell_pci
)
SELECT 'LTE neighbours' AS scope,count(*) AS identities,
       count(*) FILTER(WHERE candidates=0) AS no_candidate,
       count(*) FILTER(WHERE candidates=1) AS unique_candidate,
       count(*) FILTER(WHERE candidates>1) AS ambiguous_candidates,
       min(candidates),max(candidates)
FROM candidate_counts;

WITH identities AS (
  SELECT DISTINCT cell_pci
  FROM nmf_cell_identity
  WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e'
    AND system=9 AND cell_type=199
), candidate_counts AS (
  SELECT i.cell_pci,count(r.id) AS candidates
  FROM identities i
  LEFT JOIN cell_ref r
    ON upper(r.techno)='5G' AND r.earfcn=3500
   AND r.pci=i.cell_pci AND r.geom IS NOT NULL
  GROUP BY i.cell_pci
)
SELECT 'NR PSCell' AS scope,count(*) AS identities,
       count(*) FILTER(WHERE candidates=0) AS no_candidate,
       count(*) FILTER(WHERE candidates=1) AS unique_candidate,
       count(*) FILTER(WHERE candidates>1) AS ambiguous_candidates,
       min(candidates),max(candidates)
FROM candidate_counts;
COMMIT;
