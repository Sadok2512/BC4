
WITH eligible AS (
 SELECT DISTINCT system,param_key FROM param_occurrence
 WHERE project_id='134af70a06eb' AND origin='network_config'
 AND NOT COALESCE(is_identifier,false) AND param_key IS NOT NULL
 AND NOT(regexp_replace(path,'^.*/','') ~ '^(spare[0-9]*|dummy|reserved)$')
)
SELECT count(*) eligible_keys,
count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM dict_category_map m WHERE m.technology=e.system
 AND(e.param_key=m.path_prefix OR starts_with(e.param_key,m.path_prefix||'/')))) autres_keys
FROM eligible e;
