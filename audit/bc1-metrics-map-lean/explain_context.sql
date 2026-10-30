EXPLAIN (ANALYZE, BUFFERS)
WITH mp AS (
  SELECT capture_id,seq,
    CASE WHEN count(DISTINCT operator)=1 THEN min(operator) END AS operator,
    CASE WHEN count(DISTINCT band)=1 THEN min(band) END AS band,
    CASE WHEN count(DISTINCT tech)=1 THEN min(tech) END AS tech,
    CASE WHEN count(DISTINCT rat)=1 THEN min(rat) END AS rat,
    CASE WHEN count(DISTINCT service_type)=1 THEN min(service_type) END AS service_type,
    CASE WHEN count(DISTINCT phase)=1 THEN min(phase) END AS phase,
    CASE WHEN count(DISTINCT env)=1 THEN min(env) END AS env,
    CASE WHEN count(DISTINCT dep)=1 THEN min(dep) END AS dep,
    CASE WHEN count(DISTINCT ecgi)=1 THEN min(ecgi) END AS ecgi,
    CASE WHEN count(DISTINCT ecgi_source)=1 THEN min(ecgi_source) END AS ecgi_source
  FROM measurement_points
  WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e'
  GROUP BY capture_id,seq
), raw AS (
  SELECT capture_id,seq,nmf_file_id,system FROM stg_event_raw
  WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e'
  UNION
  SELECT capture_id,seq,nmf_file_id,system FROM stg_event
  WHERE project_id='43e81a34a073' AND capture_id='a4b0c321c52e'
), file_op AS (
  SELECT r.capture_id,r.seq,
    CASE WHEN count(DISTINCT r.system)=1 THEN min(r.system) END system,
    CASE WHEN count(DISTINCT d.operator)=1 THEN min(d.operator) END operator
  FROM raw r
  JOIN nmf_file n ON n.id=r.nmf_file_id AND n.project_id='43e81a34a073'
  LEFT JOIN (VALUES ('OFR','Orange'),('BYT','Bouygues'),('FREE','Free'),('SFR','SFR'))
    d(dl,operator) ON d.dl=upper(trim(n.dl))
  GROUP BY r.capture_id,r.seq
), rrc AS (
  SELECT e.capture_id,e.seq,
    CASE WHEN count(DISTINCT p.operator)=1 THEN min(p.operator) END operator
  FROM stg_event e
  JOIN param_occurrence p ON p.project_id=e.project_id AND p.stg_event_id=e.id
  WHERE e.project_id='43e81a34a073' AND e.capture_id='a4b0c321c52e'
  GROUP BY e.capture_id,e.seq
)
SELECT coalesce(f.capture_id,m.capture_id) capture_id,
  coalesce(f.seq,m.seq) seq,coalesce(f.operator,m.operator,r.operator) operator,
  m.band,m.tech,m.rat,m.service_type,m.phase,m.env,m.dep,m.ecgi,m.ecgi_source
FROM file_op f FULL JOIN mp m USING(capture_id,seq)
LEFT JOIN rrc r ON r.capture_id=coalesce(f.capture_id,m.capture_id)
 AND r.seq=coalesce(f.seq,m.seq);
