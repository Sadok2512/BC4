COPY (
WITH keys AS (
 SELECT system,message,param_key,count(*) n_occurrences
 FROM param_occurrence
 WHERE project_id='134af70a06eb' AND NOT COALESCE(is_identifier,false)
 AND param_key IS NOT NULL
 GROUP BY system,message,param_key
), classified AS (
 SELECT k.*,coalesce(m.category_id,'autres') category_id
 FROM keys k LEFT JOIN LATERAL (
 SELECT category_id FROM dict_category_map m
 WHERE m.technology=k.system AND (k.param_key=m.path_prefix OR starts_with(k.param_key,m.path_prefix||'/'))
 ORDER BY length(m.path_prefix) DESC LIMIT 1
 ) m ON true
)
SELECT system,message,array_to_string((string_to_array(param_key,'/'))[1:4],'/') AS asn1_prefix,
param_key,n_occurrences FROM classified WHERE category_id='autres'
ORDER BY system,message,asn1_prefix,param_key
) TO STDOUT WITH CSV HEADER;
