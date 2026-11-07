"""Lean, capture-scoped metric map projection.

The table analysis still owns histograms, CSV and tabular pagination.  A map
does not need any of those products, so this module builds only the proven
points from already loaded metric rows.  Ordering is always
``(project_id, capture_id, seq)`` and every query carries both identifiers.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable

from sqlalchemy import text

from app.db import SessionLocal
from app.kpi.map_cell_links import (
    enrich_metric_role_serving_links,
    enrich_probable_neighbour_nr_links,
    enrich_probable_serving_links,
    enrich_radio_links,
    load_probable_reference_lookup,
    metric_serving_identity,
)


log = logging.getLogger(__name__)


def _pair_previous_or_same(xs: list[dict], ys: Iterable[dict]):
    index = 0
    previous = None
    for item in ys:
        while index < len(xs) and xs[index]["seq"] <= item["seq"]:
            previous = xs[index]
            index += 1
        yield item, previous


def load_gps_fixes(dataset) -> list[dict]:
    return [dict(row) for row in dataset.query("""
        SELECT seq,lat,lon FROM stg_event_raw
        WHERE project_id=:pid AND capture_id=:cap AND event_code='GPS'
          AND lat IS NOT NULL AND lon IS NOT NULL AND NOT(lat=0 AND lon=0)
        ORDER BY project_id,capture_id,seq
    """)]


def load_gps_fixes_scoped(project_id: str, capture_id: str) -> list[dict]:
    """Independent read used in parallel with the metric projection."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT seq,lat,lon FROM stg_event_raw
            WHERE project_id=:pid AND capture_id=:cap AND event_code='GPS'
              AND lat IS NOT NULL AND lon IS NOT NULL AND NOT(lat=0 AND lon=0)
            ORDER BY project_id,capture_id,seq
        """), {"pid": project_id, "cap": capture_id}).mappings()
        return [dict(row) for row in rows]


def build_map_points(
    dataset,
    loaded: list[tuple[dict, list[dict]]],
    gps_fixes: list[dict],
    *,
    returned_by_selection: dict[str, set[int]] | None = None,
) -> list[dict]:
    """Build the same point contract as ``include_map`` without table work."""
    chi_rows = [dict(row) for row in dataset.query("""
        SELECT seq, raw_fields->>'c9' AS eci
        FROM stg_event_raw
        WHERE project_id=:pid AND capture_id=:cap
          AND event_code='CHI' AND system='LTE'
          AND raw_fields->>'c9' ~ '^[0-9]+$'
        ORDER BY project_id,capture_id,seq
    """)]
    cell_ids = sorted({row["eci"] for row in chi_rows})
    cell_refs = {}
    if cell_ids:
        cell_refs = {row["eci"]: dict(row) for row in dataset.query("""
            SELECT eci,id AS cell_ref_id,site_id,site_name,
                   ST_Y(geom) AS lat,ST_X(geom) AS lng
            FROM cell_ref
            WHERE eci=ANY(:serving_ecgis) AND geom IS NOT NULL
            ORDER BY eci,id
        """, {"serving_ecgis": cell_ids})}

    rows_for_map = []
    for metric, rows in loaded:
        for row, chi in _pair_previous_or_same(chi_rows, rows):
            if row["value"] is None:
                continue
            if (returned_by_selection is not None
                    and row["seq"] not in returned_by_selection.get(metric["selection"], set())):
                continue
            rows_for_map.append((metric, row, chi))

    keyed = [{"seq": row["seq"], "tuple": (metric, row, chi)}
             for metric, row, chi in rows_for_map]
    keyed.sort(key=lambda item: item["seq"])
    points = []
    for item, fix in _pair_previous_or_same(gps_fixes, keyed):
        if fix is None:
            continue
        metric, row, chi = item["tuple"]
        position_source = "exact" if fix["seq"] == row["seq"] else "previous_fix"
        delta_seq = row["seq"] - fix["seq"]
        reference = cell_refs.get(chi["eci"]) if chi else None
        identity_cell_type, cell_role = metric_serving_identity(metric)
        tooltip = (
            f"{metric['label']} · seq {row['seq']} · {row['value']} {metric['unit']}"
            + (f" · position héritée du fix seq {fix['seq']} (Δseq {delta_seq})"
               if position_source == "previous_fix" else "")
        )
        points.append({
            "seq": row["seq"], "lat": fix["lat"], "lng": fix["lon"],
            "code": metric["selection"], "_second": row["second"],
            "value": row["value"], "t_rel_s": row["t_rel_s"],
            "position_source": position_source, "delta_seq": delta_seq,
            "position_fix_seq": fix["seq"], "tooltip": tooltip,
            "serving_cell_id": chi["eci"] if reference else None,
            "serving_cell_seq": chi["seq"] if reference else None,
            "serving_cell_ref_id": reference["cell_ref_id"] if reference else None,
            "serving_site_id": reference["site_id"] if reference else None,
            "serving_site_name": reference["site_name"] if reference else None,
            "serving_cell_lat": reference["lat"] if reference else None,
            "serving_cell_lng": reference["lng"] if reference else None,
            "serving_cell_source": (
                "chi_previous_seq_cell_ref_exact" if reference else None
            ),
            "serving_cell_role": cell_role,
            "_identity_cell_type": identity_cell_type,
            "_cell_role": cell_role,
        })

    seconds_by_seq = {
        int(point["seq"]): int(point["_second"])
        for point in points if point.get("_second") is not None
    }
    link_started = time.perf_counter()
    from app.kpi.probable_link_materialized import apply_materialized
    materialized = apply_materialized(dataset.db, dataset.pid, dataset.cap, points)
    if not materialized:
        enrich_radio_links(dataset.db, dataset.pid, dataset.cap, points)
        after_proven = time.perf_counter()
        # 0.117.0 BC3 — fallback probable pour serving quand pas d'EARFCN
        # exact dans cell_ref (band + PCI + proximité <= 10 km).
        probable_lookup = load_probable_reference_lookup(dataset.db, points)
        enrich_probable_serving_links(
            dataset.db, dataset.pid, dataset.cap, points, probable_lookup
        )
        after_serving = time.perf_counter()
        enrich_probable_neighbour_nr_links(
            dataset.db, dataset.pid, dataset.cap, points, seconds_by_seq, probable_lookup
        )
    else:
        after_proven = time.perf_counter()
        after_serving = after_proven
    # MAC metrics have an explicit PCell/SCell role and cannot safely reuse a
    # PCell-only cache row. Resolve their matching CELLMEAS identity in one
    # batched query for both fresh and materialized-cache paths.
    if points:
        role_lookup = load_probable_reference_lookup(dataset.db, points)
        enrich_metric_role_serving_links(
            dataset.db, dataset.pid, dataset.cap, points, role_lookup
        )
    after_probable = time.perf_counter()
    log.info(
        "metrics map link stages project=%s capture=%s points=%d "
        "proven_ms=%.3f serving_probable_ms=%.3f neighbour_nr_probable_ms=%.3f total_ms=%.3f",
        dataset.pid, dataset.cap, len(points),
        (after_proven - link_started) * 1000,
        (after_serving - after_proven) * 1000,
        (after_probable - after_serving) * 1000,
        (after_probable - link_started) * 1000,
    )
    return points
