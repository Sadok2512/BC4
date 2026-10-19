WITH keys AS (
 SELECT project_id,system,message,param_key,discriminators,count(*) n_occurrences
 FROM param_occurrence WHERE project_id IN ('134af70a06eb','4b7bfd50ddb6')
 AND NOT COALESCE(is_identifier,false) AND param_key IS NOT NULL
 GROUP BY project_id,system,message,param_key,discriminators
), classified AS (
 SELECT k.*,coalesce(m.category_id,'autres') category_id
 FROM keys k LEFT JOIN LATERAL (
 SELECT category_id FROM dict_category_map m
 WHERE m.technology=k.system AND (k.param_key=m.path_prefix OR starts_with(k.param_key,m.path_prefix||'/'))
 ORDER BY length(m.path_prefix) DESC LIMIT 1
 ) m ON true
)
SELECT project_id,message,count(*) AS leaves,count(*) FILTER(WHERE category_id='autres') AS autres_leaves,
count(DISTINCT (system,param_key)) AS keys,count(DISTINCT (system,param_key)) FILTER(WHERE category_id='autres') AS autres_keys,
sum(n_occurrences) AS occurrences
FROM classified GROUP BY project_id,ROLLUP(message) ORDER BY project_id,message;
