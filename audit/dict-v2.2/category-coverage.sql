WITH keys AS (
 SELECT project_id,system,origin,param_key
 FROM param_occurrence WHERE project_id IN ('134af70a06eb','4b7bfd50ddb6')
 AND NOT COALESCE(is_identifier,false) AND param_key IS NOT NULL
 GROUP BY project_id,system,origin,param_key
), classified AS (
 SELECT k.*,NOT EXISTS(
 SELECT 1 FROM dict_category_map m WHERE m.technology=k.system
 AND (k.param_key=m.path_prefix OR starts_with(k.param_key,m.path_prefix||'/'))
 ) AS autres FROM keys k
)
SELECT project_id,origin,count(*) keys,count(*) FILTER(WHERE autres) autres_keys,
round(100.0*count(*) FILTER(WHERE autres)/NULLIF(count(*),0),2) autres_pct
FROM classified GROUP BY project_id,ROLLUP(origin) ORDER BY project_id,origin;
