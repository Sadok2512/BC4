WITH leaves AS (
 SELECT project_id,system,message,functional_group,param_key,display_name,choice_of,discriminators,unit_converted,is_identifier,count(*) n
 FROM param_occurrence
 WHERE project_id IN ('134af70a06eb','4b7bfd50ddb6') AND message='RRCConnectionReconfiguration' AND param_key IS NOT NULL AND NOT COALESCE(is_identifier,false)
 GROUP BY project_id,system,message,functional_group,param_key,display_name,choice_of,discriminators,unit_converted,is_identifier
)
SELECT project_id,count(*) leaves,count(*) FILTER(WHERE NOT EXISTS (
 SELECT 1 FROM dict_category_map m WHERE m.technology=l.system AND (l.param_key=m.path_prefix OR starts_with(l.param_key,m.path_prefix||'/'))
)) autres FROM leaves l GROUP BY project_id;
