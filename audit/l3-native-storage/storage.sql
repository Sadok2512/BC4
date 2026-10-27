\pset pager off
\echo 'Q1 witnesses: source records vs current 1-second light rows'
WITH witnesses(capture_id) AS (VALUES ('44621571bccc'),('e84832b42679'),('289784700e72'))
SELECT c.project_id,c.capture_id,c.decode_level,c.n_records AS native_rows,
       COALESCE(l.current_light_rows,0) AS current_light_rows,
       COALESCE(l.verified_light_buckets,0) AS verified_light_buckets,
       COALESCE(r.staged_raw_rows,0) AS staged_raw_rows
FROM witnesses w JOIN nmf_capture c USING(capture_id)
LEFT JOIN LATERAL (SELECT count(*) current_light_rows,count(DISTINCT (event_code,second,dimension)) verified_light_buckets FROM nmf_event_light WHERE project_id=c.project_id AND capture_id=c.capture_id) l ON true
LEFT JOIN LATERAL (SELECT count(DISTINCT seq) staged_raw_rows FROM stg_event_raw WHERE project_id=c.project_id AND capture_id=c.capture_id) r ON true
WHERE c.project_id='4b7bfd50ddb6'
ORDER BY c.capture_id;

\echo 'Q2 physical size including all nmf_event_light partitions'
SELECT pg_total_relation_size('nmf_event_light')::bigint AS light_total_bytes,
       (SELECT count(*) FROM nmf_event_light)::bigint AS light_total_rows,
       round(pg_total_relation_size('nmf_event_light')::numeric / NULLIF((SELECT count(*) FROM nmf_event_light),0),2) AS physical_bytes_per_light_row;

\echo 'Q3 corpus 85 capture rows: current vs native rows and prorated bytes'
WITH stats AS (
 SELECT pg_total_relation_size('nmf_event_light')::numeric AS bytes,
        (SELECT count(*)::numeric FROM nmf_event_light) AS light_rows
), corpus AS (
 SELECT count(*)::bigint AS capture_rows,sum(n_records)::bigint AS native_rows FROM nmf_capture
), current AS (SELECT count(*)::bigint AS current_light_rows FROM nmf_event_light)
SELECT corpus.capture_rows,current.current_light_rows,corpus.native_rows,
       round(stats.bytes/stats.light_rows,2) AS bytes_per_row,
       round(current.current_light_rows*stats.bytes/stats.light_rows)::bigint AS current_prorated_bytes,
       round(corpus.native_rows*stats.bytes/stats.light_rows)::bigint AS native_prorated_bytes,
       round(corpus.native_rows::numeric/NULLIF(current.current_light_rows,0),2) AS native_to_current_ratio
FROM corpus,current,stats;

\echo 'Q4 per-witness prorated bytes using measured physical bytes/row'
WITH stats AS (SELECT pg_total_relation_size('nmf_event_light')::numeric/(SELECT count(*) FROM nmf_event_light) bpr),
w(capture_id) AS (VALUES ('44621571bccc'),('e84832b42679'),('289784700e72')),
rows AS (
 SELECT c.capture_id,c.n_records::bigint native_rows,count(l.*)::bigint current_rows
 FROM w JOIN nmf_capture c USING(capture_id)
 LEFT JOIN nmf_event_light l ON l.project_id=c.project_id AND l.capture_id=c.capture_id
 WHERE c.project_id='4b7bfd50ddb6' GROUP BY c.capture_id,c.n_records
)
SELECT capture_id,current_rows,native_rows,round(current_rows*bpr)::bigint current_prorated_bytes,
       round(native_rows*bpr)::bigint native_prorated_bytes,
       round(native_rows::numeric/NULLIF(current_rows,0),2) ratio
FROM rows,stats ORDER BY capture_id;
