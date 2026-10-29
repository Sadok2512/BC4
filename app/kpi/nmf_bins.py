"""Capture-local query-time bins over Deep or compact native Light."""
from __future__ import annotations

import re
from sqlalchemy import text

from app.config import settings
from app.nmf_decoder.schema import fields

TEMPORAL_SECONDS = {"1ms": .001, "10ms": .01, "100ms": .1, "1s": 1.0}
SPATIAL_METERS = {10, 25, 50, 100}


def capture_resolution(db, project_id, capture_id, mode=None, temporal=None, spatial=None):
    snapshot = db.execute(text("""SELECT decode_level,binning_mode,temporal_resolution,spatial_bin_m
      FROM nmf_capture WHERE project_id=:pid AND capture_id=:cap"""),
      {"pid": project_id, "cap": capture_id}).mappings().one()
    selected_mode = mode or snapshot["binning_mode"] or "temporal"
    selected_temporal = temporal if temporal is not None else snapshot["temporal_resolution"]
    selected_spatial = spatial if spatial is not None else snapshot["spatial_bin_m"]
    if selected_mode == "temporal":
        selected_temporal = selected_temporal or "native"
        if selected_temporal not in {"native", *TEMPORAL_SECONDS}:
            raise ValueError("invalid_temporal_resolution")
        selected_spatial = None
    elif selected_mode == "spatial":
        if selected_spatial not in SPATIAL_METERS:
            raise ValueError("invalid_spatial_resolution")
        selected_temporal = None
    else:
        raise ValueError("invalid_binning_mode")
    return dict(snapshot, mode=selected_mode, temporal=selected_temporal, spatial=selected_spatial)


def _source_sql(level, column):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", column) or column not in fields():
        raise ValueError("unknown_metric_column")
    if level == "light":
        return """SELECT project_id,capture_id,seq,t_rel_s,
          CASE WHEN values ? :column THEN (values->>:column)::double precision END value,
          x_2154,y_2154,position_source,position_gap_s,position_reason
          FROM nmf_event_light_native WHERE project_id=:pid AND capture_id=:cap"""
    return f"""WITH base AS (
        SELECT d.project_id,d.capture_id,d.seq,d.t_rel_s,d.event_code,d.tokens,
          d.\"{column}\"::double precision metric_value,
          CASE WHEN event_code='GPS' AND tokens[4] ~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$'
            AND tokens[5] ~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$' THEN tokens[4]::double precision END fix_lon,
          CASE WHEN event_code='GPS' AND tokens[4] ~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$'
            AND tokens[5] ~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$' THEN tokens[5]::double precision END fix_lat
        FROM nmf_event_deep d WHERE project_id=:pid AND capture_id=:cap
      ), tagged AS (
        SELECT base.*,max(seq) FILTER(WHERE fix_lon IS NOT NULL AND fix_lat IS NOT NULL)
          OVER(PARTITION BY project_id,capture_id ORDER BY seq ROWS UNBOUNDED PRECEDING) fix_seq
        FROM base
      )
      SELECT d.project_id,d.capture_id,d.seq,d.t_rel_s,d.metric_value value,
        CASE WHEN f.seq IS NULL THEN NULL ELSE ST_X(ST_Transform(ST_SetSRID(ST_Point(f.lon,f.lat),4326),2154)) END x_2154,
        CASE WHEN f.seq IS NULL THEN NULL ELSE ST_Y(ST_Transform(ST_SetSRID(ST_Point(f.lon,f.lat),4326),2154)) END y_2154,
        CASE WHEN f.seq=d.seq THEN 'exact' WHEN f.seq IS NOT NULL THEN 'previous_fix' END position_source,
        CASE WHEN f.seq IS NULL THEN NULL ELSE abs(d.t_rel_s-f.t_rel_s) END position_gap_s,
        CASE WHEN d.t_rel_s IS NULL THEN 'time_missing'
             WHEN f.seq IS NULL THEN 'no_fix_within_gap' END position_reason
      FROM tagged d LEFT JOIN (
        SELECT project_id,capture_id,seq,t_rel_s,fix_lon lon,fix_lat lat FROM tagged
        WHERE fix_lon IS NOT NULL AND fix_lat IS NOT NULL
      ) f ON f.project_id=d.project_id AND f.capture_id=d.capture_id AND f.seq=d.fix_seq
        AND d.t_rel_s IS NOT NULL AND abs(d.t_rel_s-f.t_rel_s)<=:max_gap"""


def query_metric_bins(db, project_id, capture_id, column, *, mode=None, temporal=None, spatial=None):
    resolution = capture_resolution(db, project_id, capture_id, mode, temporal, spatial)
    source = _source_sql(resolution["decode_level"], column)
    params = {"pid": project_id, "cap": capture_id, "column": column,
              "max_gap": settings.spatial_fix_max_gap_s}
    if resolution["mode"] == "temporal" and resolution["temporal"] == "native":
        sql = f"""WITH source AS ({source}) SELECT capture_id,seq seq_start,seq seq_end,
          1 n_records,(value IS NOT NULL)::int n_valid,
          (position_source='exact')::int n_exact,
          (position_source='previous_fix')::int n_inherited,
          t_rel_s bin_start,value,x_2154,y_2154,position_source,position_reason
          FROM source ORDER BY project_id,capture_id,seq"""
    elif resolution["mode"] == "temporal":
        params["delta"] = TEMPORAL_SECONDS[resolution["temporal"]]
        sql = f"""WITH source AS ({source}), population AS (
          SELECT *,floor(t_rel_s/:delta) bin FROM source
        ) SELECT capture_id,min(seq) seq_start,max(seq) seq_end,count(*) n_records,
          count(value) n_valid,count(*) FILTER(WHERE position_source='exact') n_exact,
          count(*) FILTER(WHERE position_source='previous_fix') n_inherited,
          bin*:delta bin_start,
          percentile_cont(.5) WITHIN GROUP(ORDER BY value) FILTER(WHERE value IS NOT NULL) value,
          NULL::double precision x_2154,NULL::double precision y_2154,NULL::text position_source,
          CASE WHEN bin IS NULL THEN 'time_missing' END position_reason
          FROM population GROUP BY capture_id,bin ORDER BY capture_id,bin NULLS LAST"""
    else:
        params["size"] = resolution["spatial"]
        sql = f"""WITH source AS ({source}), population AS (
          SELECT *,floor(x_2154/:size) bx,floor(y_2154/:size) by FROM source
        ) SELECT capture_id,min(seq) seq_start,max(seq) seq_end,count(*) n_records,
          count(value) n_valid,count(*) FILTER(WHERE position_source='exact') n_exact,
          count(*) FILTER(WHERE position_source='previous_fix') n_inherited,
          NULL::double precision bin_start,
          percentile_cont(.5) WITHIN GROUP(ORDER BY value) FILTER(WHERE value IS NOT NULL) value,
          bx*:size x_2154,by*:size y_2154,NULL::text position_source,
          CASE WHEN bx IS NULL THEN min(position_reason) END position_reason
          FROM population GROUP BY capture_id,bx,by ORDER BY capture_id,bx NULLS LAST,by NULLS LAST"""
    rows = [dict(row) for row in db.execute(text(sql), params).mappings()]
    return resolution, rows
