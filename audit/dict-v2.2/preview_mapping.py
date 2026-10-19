"""Generate and execute a read-only SQL audit of the draft seed against TEST2."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=root/"audit/dict-v2.2"
seed=json.loads((root/"app/dict/config/categories_v22.json").read_text())
literal=json.dumps(seed["maps"],ensure_ascii=False).replace("'","''")
cte=f"""
WITH mappings AS (
 SELECT * FROM jsonb_to_recordset('{literal}'::jsonb)
 AS m(technology text,path_prefix text,category_id text,subcategory_id text,discriminator jsonb,note text)
), eligible AS (
 SELECT *,regexp_replace(path,'\\[[0-9]+\\]','[*]','g') AS normalized
 FROM param_occurrence WHERE project_id='134af70a06eb'
 AND origin='network_config' AND param_key IS NOT NULL AND NOT COALESCE(is_identifier,false)
 AND NOT(regexp_replace(path,'^.*/','') ~ '^(spare[0-9]*|dummy|reserved)$')
), classified AS (
 SELECT e.*,m.category_id,m.subcategory_id FROM eligible e
 LEFT JOIN LATERAL(
 SELECT category_id,subcategory_id FROM mappings m
 WHERE m.technology IN(e.system,'BOTH')
 AND (e.normalized=m.path_prefix OR starts_with(e.normalized,m.path_prefix||'/'))
 AND COALESCE(e.discriminators,'{{}}'::jsonb) @> m.discriminator
 ORDER BY length(m.path_prefix) DESC,(SELECT count(*) FROM jsonb_object_keys(m.discriminator)) DESC,
 (m.technology=e.system) DESC LIMIT 1
 ) m ON true
), keys AS (
 SELECT system,param_key,bool_and(category_id IS NOT NULL) fully_mapped,
 bool_or(category_id IS NULL) unresolved,bool_or(category_id='autres') explicit_autres
 FROM classified GROUP BY system,param_key
)
"""
sql=cte+"""
SELECT count(*) eligible_keys,count(*) FILTER(WHERE fully_mapped) fully_mapped_keys,
count(*) FILTER(WHERE unresolved) unresolved_keys,count(*) FILTER(WHERE explicit_autres) explicit_autres_keys,
round(100.0*count(*) FILTER(WHERE unresolved OR explicit_autres)/NULLIF(count(*),0),2) unresolved_or_autres_pct,
(SELECT count(*) FROM classified) eligible_occurrences,
(SELECT count(*) FROM classified WHERE category_id IS NULL) unresolved_occurrences
FROM keys;
"""
(out/"seed-preview.sql").write_text(sql)
r=subprocess.run(["docker","exec","-i","bc4-db-1","psql","-U","bc4","-d","bc4","-X","-v","ON_ERROR_STOP=1"],input=sql,text=True,capture_output=True,check=True)
(out/"seed-preview.txt").write_text(r.stdout);print(r.stdout)
# The original v2.1 comparison uses the SAME new eligible population.
before="""
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
"""
(out/"eligible-before.sql").write_text(before)
r=subprocess.run(["docker","exec","-i","bc4-db-1","psql","-U","bc4","-d","bc4","-X","-v","ON_ERROR_STOP=1"],input=before,text=True,capture_output=True,check=True)
(out/"eligible-before.txt").write_text(r.stdout);print(r.stdout)
