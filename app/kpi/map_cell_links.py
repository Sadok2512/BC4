"""Proven neighbour and EN-DC anchor links for metric map points.

Neighbour identity is read at the measurement's exact ``seq`` from
``nmf_cell_identity``; PSCell is read in the same capture-second because the
LTE and NR CELLMEAS records have distinct seq values. ``cell_ref.earfcn`` is
currently a band-frequency key (700/800/1800/...) rather than a raw channel,
so the measured ARFCN is deterministically normalized before matching
``(system, band, PCI)``.  The closest duplicate within 25 km wins.  A
missing/out-of-range match produces no link.
"""
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import text


MAX_CELL_LINK_DISTANCE_M = 25_000.0
LTE_NEIGHBOUR_TYPES = (1, 2)
NR_NEIGHBOUR_TYPES = (1000, 1001, 1002)
NR_ANCHOR_TYPE = 199


def _reference_channel(system: int, arfcn: int) -> int | None:
    """Map 3GPP ARFCN to the band-frequency vocabulary stored by cell_ref."""
    if system == 7:
        # LTE E-UTRA ranges whose French band keys exist in cell_ref.
        for lo, hi, channel in (
            (0, 599, 2100),       # band 1
            (1200, 1949, 1800),   # band 3
            (2750, 3449, 2600),   # band 7
            (3450, 3799, 900),    # band 8
            (5010, 5379, 700),    # bands 12-14
            (5730, 5849, 700),    # band 17
            (6150, 6449, 800),    # band 20
            (9040, 9209, 800),    # band 27
            (9210, 9659, 700),    # band 28
            (9660, 9769, 700),    # band 29
        ):
            if lo <= arfcn <= hi:
                return channel
        return None
    if system == 9:
        # NR operating ranges represented by the French reference import.
        for lo, hi, channel in (
            (151600, 160600, 700),    # n28
            (361000, 376000, 1800),   # n3
            (422000, 434000, 2100),   # n1
            (524000, 538000, 2600),   # n7
            (620000, 680000, 3500),   # n77/n78
        ):
            if lo <= arfcn <= hi:
                return channel
        return None
    return None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance, deterministic and independent of PostGIS."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 6_371_008.8 * 2 * asin(sqrt(a))


def enrich_radio_links(db, project_id: str, capture_id: str, map_points: list[dict]) -> None:
    """Mutate map points with optional proven links, scoped to one capture."""
    if not map_points:
        return
    points_by_seq: dict[int, list[dict]] = defaultdict(list)
    for point in map_points:
        points_by_seq[int(point["seq"])].append(point)
        point.setdefault("neighbour_links", [])
        point.setdefault("nr_anchor_link", None)

    identities = list(db.execute(text("""
        SELECT seq,system,cell_type,cell_arfcn,cell_pci
        FROM nmf_cell_identity
        WHERE project_id=:pid AND capture_id=:cap AND event_code='CELLMEAS'
          AND seq=ANY(:seqs)
          AND cell_arfcn IS NOT NULL AND cell_pci IS NOT NULL
          AND ((system=7 AND cell_type=ANY(:lte_types))
            OR (system=9 AND cell_type=ANY(:nr_types)))
        ORDER BY project_id,capture_id,seq,system,cell_type,cell_arfcn,cell_pci
    """), {
        "pid": project_id,
        "cap": capture_id,
        "seqs": sorted(points_by_seq),
        "lte_types": list(LTE_NEIGHBOUR_TYPES),
        "nr_types": [*NR_NEIGHBOUR_TYPES, NR_ANCHOR_TYPE],
    }).mappings())
    points_with_second=[p for p in map_points if p.get("_second") is not None]
    if points_with_second:
        identities.extend(db.execute(text("""
            WITH targets AS (
              SELECT * FROM unnest(CAST(:target_seqs AS integer[]),CAST(:seconds AS integer[]))
                AS t(target_seq,second)
            )
            SELECT DISTINCT t.target_seq AS seq,i.system,i.cell_type,i.cell_arfcn,i.cell_pci
            FROM targets t
            JOIN nmf_event_light l
              ON l.project_id=:pid AND l.capture_id=:cap AND l.second=t.second
             AND l.event_code='CELLMEAS'
            JOIN nmf_cell_identity i
              ON i.project_id=l.project_id AND i.capture_id=l.capture_id
             AND i.seq=l.seq AND i.event_code=l.event_code
            WHERE i.system=9 AND i.cell_type=:anchor_type
              AND i.cell_arfcn IS NOT NULL AND i.cell_pci IS NOT NULL
            ORDER BY t.target_seq,i.system,i.cell_type,i.cell_arfcn,i.cell_pci
        """), {
            "pid": project_id,
            "cap": capture_id,
            "target_seqs": [int(p["seq"]) for p in points_with_second],
            "seconds": [int(p["_second"]) for p in points_with_second],
            "anchor_type": NR_ANCHOR_TYPE,
        }).mappings())
    wanted = sorted({(int(r["system"]), int(r["cell_arfcn"]), int(r["cell_pci"]),
                      _reference_channel(int(r["system"]),int(r["cell_arfcn"])))
                     for r in identities
                     if _reference_channel(int(r["system"]),int(r["cell_arfcn"])) is not None})
    if not wanted:
        return
    refs = list(db.execute(text("""
        WITH wanted AS (
          SELECT * FROM unnest(
            CAST(:systems AS smallint[]),CAST(:arfcns AS bigint[]),
            CAST(:pcis AS integer[]),CAST(:reference_channels AS integer[])
          ) AS w(system,arfcn,pci,reference_channel)
        )
        SELECT w.system,w.arfcn,w.pci,w.reference_channel,
               r.id AS cell_ref_id,r.site_id,r.site_name,
               ST_Y(r.geom) AS lat,ST_X(r.geom) AS lng
        FROM wanted w
        JOIN cell_ref r ON r.earfcn=w.reference_channel AND r.pci=w.pci
          AND ((w.system=7 AND upper(COALESCE(r.techno,r.rat)) IN ('4G','LTE'))
            OR (w.system=9 AND upper(COALESCE(r.techno,r.rat)) IN ('5G','NR')))
        WHERE r.geom IS NOT NULL
        ORDER BY w.system,w.arfcn,w.pci,r.id
    """), {
        "systems": [v[0] for v in wanted],
        "arfcns": [v[1] for v in wanted],
        "pcis": [v[2] for v in wanted],
        "reference_channels": [v[3] for v in wanted],
    }).mappings())
    refs_by_identity: dict[tuple[int, int, int], list] = defaultdict(list)
    for ref in refs:
        refs_by_identity[(int(ref["system"]), int(ref["arfcn"]), int(ref["pci"]))].append(ref)

    seen: dict[int, set[tuple[int, int, int, int]]] = defaultdict(set)
    for identity in identities:
        seq = int(identity["seq"])
        system = int(identity["system"])
        arfcn = int(identity["cell_arfcn"])
        pci = int(identity["cell_pci"])
        cell_type = int(identity["cell_type"])
        reference_channel = _reference_channel(system, arfcn)
        if reference_channel is None:
            continue
        identity_key = (system, cell_type, arfcn, pci)
        if identity_key in seen[seq]:
            continue
        seen[seq].add(identity_key)
        candidates = refs_by_identity.get((system, arfcn, pci), [])
        for point in points_by_seq[seq]:
            ranked = sorted(
                ((_distance_m(point["lat"], point["lng"], ref["lat"], ref["lng"]), ref)
                 for ref in candidates),
                key=lambda item: (item[0], item[1]["cell_ref_id"]),
            )
            if not ranked or ranked[0][0] > MAX_CELL_LINK_DISTANCE_M:
                continue
            distance, ref = ranked[0]
            link = {
                "system": "LTE" if system == 7 else "NR",
                "arfcn": arfcn,
                "reference_channel": reference_channel,
                "pci": pci,
                "cell_type": cell_type,
                "cell_ref_id": ref["cell_ref_id"],
                "site_id": ref["site_id"],
                "site_name": ref["site_name"],
                "lat": float(ref["lat"]),
                "lng": float(ref["lng"]),
                "distance_m": round(distance, 1),
                "max_distance_m": MAX_CELL_LINK_DISTANCE_M,
                "candidate_count": len(candidates),
                "confidence": ("radio_band_pci_unique" if len(candidates) == 1
                               else "radio_band_pci_nearest_within_25000m"),
            }
            if system == 9 and cell_type == NR_ANCHOR_TYPE:
                # EN-DC is proven only when this point also has a proven LTE
                # serving cell.  A lone NR PSCell is not enough to infer a link.
                if point.get("serving_cell_ref_id"):
                    point["nr_anchor_link"] = link
            else:
                point["neighbour_links"].append(link)
    for point in map_points:
        point.pop("_second",None)
