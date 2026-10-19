WITH p AS (
 SELECT *,NOT COALESCE(is_identifier,false) AND param_key IS NOT NULL
 AND NOT (regexp_replace(path,'^.*/','') ~ '^(spare[0-9]*|dummy|reserved)$') eligible
 FROM param_occurrence WHERE project_id='134af70a06eb'
)
SELECT origin,count(*) total_rows,count(*) FILTER(WHERE eligible) eligible_occurrences,
count(DISTINCT(system,param_key)) FILTER(WHERE eligible) eligible_keys,
count(DISTINCT(system,message,path)) FILTER(WHERE eligible) eligible_paths
FROM p GROUP BY ROLLUP(origin) ORDER BY origin;
