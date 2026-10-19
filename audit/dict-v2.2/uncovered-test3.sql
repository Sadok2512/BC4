COPY (
SELECT system,message,array_to_string((string_to_array(param_key,'/'))[1:4],'/') as asn1_prefix,
param_key,display_name,choice_of,discriminators,unit_converted,functional_group,count(*) n_occurrences
FROM param_occurrence p
WHERE project_id='4b7bfd50ddb6' AND message='RRCConnectionReconfiguration'
AND param_key IS NOT NULL AND NOT COALESCE(is_identifier,false)
AND NOT EXISTS(SELECT 1 FROM dict_category_map m WHERE m.technology=p.system
AND (p.param_key=m.path_prefix OR starts_with(p.param_key,m.path_prefix||'/')))
GROUP BY system,message,param_key,display_name,choice_of,discriminators,unit_converted,functional_group,is_identifier
ORDER BY asn1_prefix,param_key,discriminators::text,unit_converted
) TO STDOUT WITH CSV HEADER;
