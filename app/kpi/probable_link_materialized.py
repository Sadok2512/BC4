"""Materialized probable map links, rebuilt without re-decoding NMF files."""
from __future__ import annotations

from datetime import datetime, timezone

import orjson
from sqlalchemy import text

from app.kpi.map_cell_links import (
    MAX_NEIGHBOUR_LINKS_PER_POINT,
    enrich_probable_neighbour_nr_links,
    enrich_probable_serving_links,
    enrich_radio_links,
    load_probable_reference_lookup,
    preserve_proven_serving_links,
)


def _reference_version(db) -> str:
    return str(db.execute(text("""
        SELECT COALESCE((SELECT id FROM reference_import
          WHERE status IN ('completed','empty') ORDER BY uploaded_at DESC,id DESC LIMIT 1),
          '__none__')
    """)).scalar_one())


def materialize_capture(db, project_id: str, capture_id: str) -> dict:
    rows = list(db.execute(text("""
        SELECT DISTINCT i.seq,m.lat,m.lng,l.second
        FROM nmf_cell_identity i
        JOIN measurement_points m
          ON m.project_id=i.project_id AND m.capture_id=i.capture_id AND m.seq=i.seq
        JOIN nmf_event_light l
          ON l.project_id=i.project_id AND l.capture_id=i.capture_id AND l.seq=i.seq
        WHERE i.project_id=:pid AND i.capture_id=:cap
          AND m.lat IS NOT NULL AND m.lng IS NOT NULL
        ORDER BY i.seq
    """), {"pid": project_id, "cap": capture_id}).mappings())
    points = [
        {"seq": int(row["seq"]), "lat": float(row["lat"]), "lng": float(row["lng"]),
         "neighbour_links": [], "nr_anchor_link": None}
        for row in rows
    ]
    seconds = {int(row["seq"]): int(row["second"]) for row in rows}
    version = _reference_version(db)
    if points:
        # Cache the proven links together with probable fallbacks.  Reading a
        # fresh cache must not repeat the exact-link query on every map call.
        enrich_radio_links(db, project_id, capture_id, points)
        lookup = load_probable_reference_lookup(db, points)
        enrich_probable_serving_links(db, project_id, capture_id, points, lookup)
        enrich_probable_neighbour_nr_links(
            db, project_id, capture_id, points, seconds, lookup
        )
    db.execute(text("""DELETE FROM nmf_probable_cell_link
      WHERE project_id=:pid AND capture_id=:cap"""), {"pid": project_id, "cap": capture_id})
    payload = []
    serving_keys = (
        "serving_cell_ref_id", "serving_site_id", "serving_site_name",
        "serving_cell_lat", "serving_cell_lng", "serving_cell_source",
        "probable_serving_cell_ref_id", "probable_serving_site_id",
        "probable_serving_site_name", "probable_serving_cell_lat",
        "probable_serving_cell_lng", "probable_serving_distance_m",
        "probable_serving_band_mhz", "probable_serving_pci",
        "probable_link_max_distance_m", "link_method", "confidence",
    )
    for point in points:
        serving = {key: point[key] for key in serving_keys if key in point}
        payload.append({
            "pid": project_id, "cap": capture_id, "seq": point["seq"],
            "version": version,
            "links": orjson.dumps({
                "serving_link": serving or None,
                "neighbour_links": point.get("neighbour_links", []),
                "nr_anchor_link": point.get("nr_anchor_link"),
            }).decode(),
        })
    if payload:
        db.execute(text("""INSERT INTO nmf_probable_cell_link
          (project_id,capture_id,seq,reference_version,link_payload)
          VALUES (:pid,:cap,:seq,:version,CAST(:links AS jsonb))"""), payload)
    db.execute(text("""INSERT INTO nmf_probable_cell_link_state
      (project_id,capture_id,reference_version,built_at)
      VALUES (:pid,:cap,:version,:built_at)
      ON CONFLICT (project_id,capture_id) DO UPDATE SET
        reference_version=EXCLUDED.reference_version,built_at=EXCLUDED.built_at"""), {
        "pid": project_id, "cap": capture_id, "version": version,
        "built_at": datetime.now(timezone.utc),
    })
    db.commit()
    return {"capture_id": capture_id, "points": len(points), "reference_version": version}


def materialize_project(db, project_id: str, capture_id: str | None = None) -> dict:
    params = {"pid": project_id}
    clause = ""
    if capture_id is not None:
        clause = " AND capture_id=:cap"
        params["cap"] = capture_id
    captures = db.execute(text("""SELECT capture_id FROM nmf_capture
      WHERE project_id=:pid""" + clause + " ORDER BY project_id,capture_id"), params).scalars()
    results = [materialize_capture(db, project_id, cap) for cap in captures]
    return {"project_id": project_id, "captures": results,
            "points": sum(item["points"] for item in results)}


def apply_materialized(db, project_id: str, capture_id: str, points: list[dict]) -> bool:
    # G56 invariant: this runs before empty/stale/missing-row branches.
    preserve_proven_serving_links(points)
    if not points:
        return True
    version = _reference_version(db)
    state = db.execute(text("""SELECT reference_version
      FROM nmf_probable_cell_link_state
      WHERE project_id=:pid AND capture_id=:cap"""), {
        "pid": project_id, "cap": capture_id,
    }).scalar_one_or_none()
    if state != version:
        return False
    rows = db.execute(text("""SELECT seq,link_payload::text AS link_payload
      FROM nmf_probable_cell_link
      WHERE project_id=:pid AND capture_id=:cap AND seq=ANY(:seqs)
      ORDER BY project_id,capture_id,seq"""), {
        "pid": project_id, "cap": capture_id,
        "seqs": sorted({int(point["seq"]) for point in points}),
    }).mappings()
    by_seq = {
        int(row["seq"]): orjson.loads(row["link_payload"])
        for row in rows
    }
    for point in points:
        stored = by_seq.get(int(point["seq"]))
        if stored is None:
            continue
        if not point.get("serving_cell_ref_id") and stored["serving_link"]:
            point.update(stored["serving_link"])
        proven = {
            (link["system"], link["arfcn"], link.get("pci"), link["cell_type"])
            for link in point.get("neighbour_links", [])
        }
        slots = max(0, MAX_NEIGHBOUR_LINKS_PER_POINT - len(point.get("neighbour_links", [])))
        for link in stored["neighbour_links"] or []:
            key = (link["system"], link["arfcn"], link.get("pci"), link["cell_type"])
            if slots and key not in proven:
                point.setdefault("neighbour_links", []).append(dict(link))
                slots -= 1
        if point.get("nr_anchor_link") is None and stored["nr_anchor_link"]:
            if point.get("serving_cell_ref_id") or point.get("probable_serving_cell_ref_id"):
                point["nr_anchor_link"] = stored["nr_anchor_link"]
    return True
