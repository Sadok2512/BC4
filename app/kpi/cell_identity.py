"""Materialize stable CELLMEAS identities from already decoded tables.

``nmf_cell_second.cell_index`` identifies a repeated set only inside one
second. It is retained as a storage join key. Public cell identity is instead
``(system, cell_arfcn, cell_pci)`` and stays stable for the whole capture.
"""
from __future__ import annotations

from sqlalchemy import text

from app.nmf_decoder.cells import CELL_ENUM, _cell_index_for


def _enum_values_sql() -> str:
    values = []
    for system, cell_type in CELL_ENUM:
        first_index = _cell_index_for(cell_type, system)
        values.append(f"({system},{cell_type},{first_index})")
    return ",".join(values)


def materialize_capture(db, project_id: str, capture_id: str) -> dict:
    """Replace one capture's mapping without reading or decoding its NMF."""
    params = {"pid": project_id, "cap": capture_id}
    decoder_version = db.execute(text("""
        SELECT decoder_version FROM nmf_capture
        WHERE project_id=:pid AND capture_id=:cap
    """), params).scalar_one()
    db.execute(text("""
        DELETE FROM nmf_cell_identity
        WHERE project_id=:pid AND capture_id=:cap
    """), params)
    enum_values = _enum_values_sql()
    result = db.execute(text(f"""
        WITH cell_enum(system,cell_type,first_index) AS (
          VALUES {enum_values}
        ), ranked AS (
          SELECT g.project_id,g.capture_id,g.seq,l.system::smallint AS system,
                 g.cell_type::integer AS cell_type,g.cell_ch,g.cell_pci,
                 row_number() OVER (
                   PARTITION BY g.project_id,g.capture_id,g.seq,l.system,g.cell_type
                   ORDER BY g.identity
                 )-1 AS occurrence
          FROM nmf_event_light_group g
          JOIN nmf_event_light l
            ON l.project_id=g.project_id AND l.capture_id=g.capture_id
           AND l.seq=g.seq AND l.event_code='CELLMEAS'
          JOIN cell_enum e
            ON e.system=l.system AND e.cell_type=g.cell_type::integer
          WHERE g.project_id=:pid AND g.capture_id=:cap
            AND g.group_name='cells'
        ), storage_cells AS (
          SELECT project_id,capture_id,seq_first,event_code,cell_index,
                 MAX(value) FILTER (WHERE metric_code='cell_rsrp') AS cell_rsrp
          FROM nmf_cell_second
          WHERE project_id=:pid AND capture_id=:cap AND event_code='CELLMEAS'
            AND cell_index>=0
          GROUP BY project_id,capture_id,seq_first,event_code,cell_index
        )
        INSERT INTO nmf_cell_identity (
          project_id,capture_id,seq,event_code,cell_index,system,cell_type,
          cell_arfcn,cell_pci,cell_rsrp,decoder_version
        )
        SELECT r.project_id,r.capture_id,r.seq,s.event_code,s.cell_index,
               r.system,r.cell_type,
               CASE WHEN r.cell_ch IS NOT NULL AND r.cell_pci IS NOT NULL
                      AND r.cell_ch=trunc(r.cell_ch)
                      AND r.cell_pci=trunc(r.cell_pci)
                    THEN r.cell_ch::bigint END,
               CASE WHEN r.cell_ch IS NOT NULL AND r.cell_pci IS NOT NULL
                      AND r.cell_ch=trunc(r.cell_ch)
                      AND r.cell_pci=trunc(r.cell_pci)
                    THEN r.cell_pci::integer END,
               s.cell_rsrp,
               :decoder_version
        FROM ranked r
        JOIN cell_enum e USING(system,cell_type)
        JOIN storage_cells s
          ON s.project_id=r.project_id AND s.capture_id=r.capture_id
         AND s.seq_first=r.seq AND s.cell_index=e.first_index+r.occurrence
        ORDER BY r.project_id,r.capture_id,r.seq,s.event_code,s.cell_index
    """), dict(params, decoder_version=decoder_version))
    stored = int(result.rowcount or 0)
    incomplete = int(db.execute(text("""
        SELECT count(*) FROM nmf_cell_identity
        WHERE project_id=:pid AND capture_id=:cap
          AND (cell_arfcn IS NULL OR cell_pci IS NULL)
    """), params).scalar_one())
    db.commit()
    return {
        "capture_id": capture_id,
        "decoder_version": decoder_version,
        "stored": stored,
        "incomplete_identity": incomplete,
    }


def materialize_project(db, project_id: str, capture_id: str | None = None) -> dict:
    params = {"pid": project_id}
    clause = ""
    if capture_id is not None:
        clause = " AND capture_id=:cap"
        params["cap"] = capture_id
    captures = db.execute(text("""
        SELECT capture_id FROM nmf_capture
        WHERE project_id=:pid
    """ + clause + " ORDER BY project_id,capture_id"), params).scalars().all()
    if not captures:
        raise LookupError("capture_not_found")
    results = [materialize_capture(db, project_id, cap) for cap in captures]
    return {
        "project_id": project_id,
        "captures": results,
        "stored": sum(item["stored"] for item in results),
        "incomplete_identity": sum(item["incomplete_identity"] for item in results),
    }
