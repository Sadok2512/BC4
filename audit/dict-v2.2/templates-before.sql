SELECT jsonb_agg(to_jsonb(t) ORDER BY t.category_id) FROM dict_template t;
