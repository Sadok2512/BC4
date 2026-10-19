SELECT
 count(*) FILTER(WHERE COALESCE(is_identifier,false)) identifier_occurrences,
 count(*) FILTER(WHERE NOT COALESCE(is_identifier,false)
   AND regexp_replace(path,'^.*/','') ~ '^(spare[0-9]*|dummy|reserved)$') padding_occurrences,
 count(*) FILTER(WHERE param_key IS NULL AND NOT COALESCE(is_identifier,false)
   AND NOT(regexp_replace(path,'^.*/','') ~ '^(spare[0-9]*|dummy|reserved)$')) missing_canonical_key
FROM param_occurrence WHERE project_id='134af70a06eb';
