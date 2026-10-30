\set ON_ERROR_STOP on
BEGIN READ ONLY;
WITH picked AS (
  SELECT DISTINCT ON (i.cell_arfcn,i.cell_pci)
    i.seq,i.cell_arfcn,i.cell_pci,
    CASE
      WHEN i.cell_arfcn BETWEEN 0 AND 599 THEN 2100
      WHEN i.cell_arfcn BETWEEN 1200 AND 1949 THEN 1800
      WHEN i.cell_arfcn BETWEEN 2750 AND 3449 THEN 2600
      WHEN i.cell_arfcn BETWEEN 3450 AND 3799 THEN 900
      WHEN i.cell_arfcn BETWEEN 6150 AND 6449 THEN 800
      WHEN i.cell_arfcn BETWEEN 9210 AND 9659 THEN 700
    END AS reference_channel
  FROM nmf_cell_identity i
  WHERE i.project_id='43e81a34a073' AND i.capture_id='a4b0c321c52e'
    AND i.system=7 AND i.cell_type IN (1,2)
  ORDER BY i.cell_arfcn,i.cell_pci,i.seq
  LIMIT 5
), positioned AS (
  SELECT p.*,g.lat,g.lon
  FROM picked p
  JOIN LATERAL (
    SELECT lat,lon FROM stg_event_raw g
    WHERE g.project_id='43e81a34a073' AND g.capture_id='a4b0c321c52e'
      AND g.event_code='GPS' AND g.seq<=p.seq
      AND g.lat IS NOT NULL AND g.lon IS NOT NULL AND NOT(g.lat=0 AND g.lon=0)
    ORDER BY g.seq DESC LIMIT 1
  ) g ON true
)
SELECT p.seq,p.cell_arfcn,p.cell_pci,p.reference_channel,
       round(ST_DistanceSphere(r.geom,ST_SetSRID(ST_MakePoint(p.lon,p.lat),4326))) AS distance_m,
       r.id AS cell_ref_id,r.site_name
FROM positioned p
JOIN LATERAL (
  SELECT * FROM cell_ref r
  WHERE upper(r.techno)='4G' AND r.earfcn=p.reference_channel
    AND r.pci=p.cell_pci AND r.geom IS NOT NULL
  ORDER BY ST_DistanceSphere(r.geom,ST_SetSRID(ST_MakePoint(p.lon,p.lat),4326)),r.id
  LIMIT 1
) r ON true
ORDER BY p.seq;
COMMIT;
