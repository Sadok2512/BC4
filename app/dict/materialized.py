"""Import-time summary used by the network-config dictionary catalogue."""
from __future__ import annotations

from uuid import uuid4
import json

from fastapi import HTTPException
from sqlalchemy import text


NORMALIZED = "regexp_replace(p.path, '\\[[0-9]+\\]', '[*]', 'g')"
ELIGIBLE = """p.param_key IS NOT NULL AND NOT COALESCE(p.is_identifier,false)
AND regexp_replace(p.path,'^.*/','') !~ '^(spare[0-9]*|dummy|reserved)$'
AND p.path NOT IN ('systemFrameNumber','mib/systemFrameNumber')"""


def materialize_network_catalog(db, project_id: str) -> dict:
    """Build a complete inactive generation, then publish it atomically."""
    if not db.execute(text("SELECT 1 FROM projects WHERE id=:pid"),
                      {"pid": project_id}).scalar():
        raise LookupError(f"project_not_found:{project_id}")
    generation = uuid4().hex
    params = {"pid": project_id, "generation": generation}

    # Reclaim only abandoned generations. The active generation remains visible
    # while the replacement is computed.
    db.execute(text("""DELETE FROM dict_network_catalog_entry e
      WHERE e.project_id=:pid AND NOT EXISTS (
        SELECT 1 FROM dict_network_catalog_state s
        WHERE s.project_id=e.project_id AND s.generation=e.generation)"""), params)
    db.commit()
    db.execute(text("""DELETE FROM dict_catalog_group_entry e
      WHERE e.project_id=:pid AND NOT EXISTS (
        SELECT 1 FROM dict_network_catalog_state s
        WHERE s.project_id=e.project_id AND s.generation=e.generation)"""), params)
    db.commit()

    db.execute(text(f"""INSERT INTO dict_network_catalog_entry (
      project_id,generation,row_no,system,message,normalized_path,param_key,
      display_name,unit_converted,choice_of,discriminators,n,captures)
      SELECT :pid,:generation,
        row_number() OVER (ORDER BY system,message,normalized_path,param_key,
          display_name,unit_converted,choice_of,discriminators::text),
        system,message,normalized_path,param_key,display_name,unit_converted,
        choice_of,discriminators,n,captures
      FROM (
        SELECT p.system,p.message,{NORMALIZED} AS normalized_path,p.param_key,
          p.display_name,p.unit_converted,p.choice_of,
          COALESCE(p.discriminators,'{{}}'::jsonb) AS discriminators,
          count(*)::bigint AS n,
          array_remove(array_agg(DISTINCT e.capture_id),NULL)::varchar[] AS captures
        FROM param_occurrence p
        LEFT JOIN stg_event e
          ON e.project_id=p.project_id AND e.id=p.stg_event_id
        WHERE p.project_id=:pid AND p.origin='network_config' AND {ELIGIBLE}
        GROUP BY p.system,p.message,{NORMALIZED},p.param_key,p.display_name,
          p.unit_converted,p.choice_of,COALESCE(p.discriminators,'{{}}'::jsonb)
      ) summarized"""), params)
    db.commit()

    db.execute(text("""INSERT INTO dict_catalog_group_entry (
      project_id,generation,row_no,system,origin,message,functional_group,
      param_key,display_name,choice_of,discriminators,unit_converted,
      is_identifier,n)
      SELECT :pid,:generation,row_number() OVER (ORDER BY system,origin,message,
        functional_group,param_key,discriminators::text),system,origin,message,
        functional_group,param_key,display_name,choice_of,discriminators,
        unit_converted,is_identifier,n
      FROM (
        SELECT system,origin,message,functional_group,param_key,display_name,
          choice_of,discriminators,unit_converted,
          COALESCE(is_identifier,false) AS is_identifier,count(*)::bigint AS n
        FROM param_occurrence
        WHERE project_id=:pid AND param_key IS NOT NULL
          AND COALESCE(is_identifier,false)=false
          AND origin IS DISTINCT FROM 'network_config'
        GROUP BY system,origin,message,functional_group,param_key,display_name,
          choice_of,discriminators,unit_converted,is_identifier
      ) grouped"""), params)
    db.commit()

    counts = db.execute(text(f"""SELECT
      count(*) FILTER (WHERE p.origin='network_config')::bigint AS source_occurrences,
      count(*) FILTER (WHERE p.origin='network_config' AND {ELIGIBLE})::bigint
        AS eligible_occurrences,
      count(*)::bigint AS total_occurrences,
      count(DISTINCT p.param_key) FILTER (WHERE p.param_key IS NOT NULL)::bigint
        AS distinct_param_keys,
      COALESCE(array_agg(DISTINCT p.message ORDER BY p.message)
        FILTER (WHERE p.message IS NOT NULL),'{{}}'::varchar[]) AS available_messages
      FROM param_occurrence p WHERE p.project_id=:pid"""), params).mappings().one()
    summary_rows = int(db.execute(text("""SELECT count(*)
      FROM dict_network_catalog_entry
      WHERE project_id=:pid AND generation=:generation"""), params).scalar() or 0)
    catalog_rows = int(db.execute(text("""SELECT count(*)
      FROM dict_catalog_group_entry
      WHERE project_id=:pid AND generation=:generation"""), params).scalar() or 0)
    from app.dict.cell_ref_group import build_group_by_options
    group_by_options = build_group_by_options(db, project_id)
    db.execute(text("""INSERT INTO dict_network_catalog_state (
      project_id,generation,source_occurrences,eligible_occurrences,summary_rows,
      total_occurrences,distinct_param_keys,available_messages,catalog_rows,
      group_by_options,built_at)
      VALUES (:pid,:generation,:source_occurrences,:eligible_occurrences,:summary_rows,
        :total_occurrences,:distinct_param_keys,:available_messages,:catalog_rows,
        CAST(:group_by_options AS jsonb),now())
      ON CONFLICT (project_id) DO UPDATE SET
        generation=excluded.generation,
        source_occurrences=excluded.source_occurrences,
        eligible_occurrences=excluded.eligible_occurrences,
        summary_rows=excluded.summary_rows,
        total_occurrences=excluded.total_occurrences,
        distinct_param_keys=excluded.distinct_param_keys,
        available_messages=excluded.available_messages,
        catalog_rows=excluded.catalog_rows,
        group_by_options=excluded.group_by_options,built_at=excluded.built_at"""),
      {**params, "source_occurrences": int(counts["source_occurrences"] or 0),
       "eligible_occurrences": int(counts["eligible_occurrences"] or 0),
       "summary_rows": summary_rows,
       "total_occurrences": int(counts["total_occurrences"] or 0),
       "distinct_param_keys": int(counts["distinct_param_keys"] or 0),
       "available_messages": list(counts["available_messages"] or []),
       "catalog_rows": catalog_rows,
       "group_by_options": json.dumps(group_by_options,sort_keys=True)})
    db.commit()

    db.execute(text("""DELETE FROM dict_network_catalog_entry
      WHERE project_id=:pid AND generation<>:generation"""), params)
    db.commit()
    db.execute(text("""DELETE FROM dict_catalog_group_entry
      WHERE project_id=:pid AND generation<>:generation"""), params)
    db.commit()
    return {"project_id": project_id, "generation": generation,
            "source_occurrences": int(counts["source_occurrences"] or 0),
            "eligible_occurrences": int(counts["eligible_occurrences"] or 0),
            "summary_rows": summary_rows,
            "total_occurrences": int(counts["total_occurrences"] or 0),
            "distinct_param_keys": int(counts["distinct_param_keys"] or 0),
            "available_messages": list(counts["available_messages"] or []),
            "catalog_rows": catalog_rows,
            "group_by_options": group_by_options}


def network_catalog_rows(db, project_id: str, message: str | None = None):
    state = db.execute(text("""SELECT generation FROM dict_network_catalog_state
      WHERE project_id=:pid"""), {"pid": project_id}).scalar()
    if state is None:
        raise HTTPException(409, detail={
            "reason": "dict_network_catalog_materialization_required",
            "project_id": project_id,
        })
    return [dict(row) for row in db.execute(text("""SELECT
      e.system,'network_config'::text AS origin,e.message,
      e.normalized_path AS path,e.param_key,e.display_name,e.unit_converted,
      e.choice_of,e.discriminators,e.n,e.captures
      FROM dict_network_catalog_entry e
      WHERE e.project_id=:pid AND e.generation=:generation
        AND (CAST(:message AS text) IS NULL OR e.message=:message)
      ORDER BY e.system,e.message,e.normalized_path,e.param_key,
        e.discriminators::text"""),
      {"pid": project_id, "generation": state, "message": message}).mappings()]
