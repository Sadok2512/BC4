SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_name IN ('dict_category','dict_category_map','dict_template','param_occurrence') ORDER BY table_name,ordinal_position;
SELECT 'dict_category' AS source,count(*) FROM dict_category UNION ALL SELECT 'dict_category_map',count(*) FROM dict_category_map UNION ALL SELECT 'dict_template',count(*) FROM dict_template;
SELECT id,name FROM projects WHERE id IN ('134af70a06eb','4b7bfd50ddb6');
SELECT project_id,count(*) AS n_occurrences,count(DISTINCT param_key) AS n_keys FROM param_occurrence WHERE project_id IN ('134af70a06eb','4b7bfd50ddb6') GROUP BY project_id;
SELECT * FROM dict_category ORDER BY position;
SELECT version_num FROM alembic_version;
