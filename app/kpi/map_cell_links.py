"""Proven neighbour and EN-DC anchor links for metric map points.

Neighbour identity is read at the measurement's exact ``seq`` from
``nmf_cell_identity``; PSCell is read in the same capture-second because the
LTE and NR CELLMEAS records have distinct seq values. Reference identity is
matched only on the exact channel: ``cell_ref.earfcn`` for LTE and
``cell_ref.nr_arfcn`` for NR, plus PCI and system. ``band_mhz`` is never a
link key. The closest duplicate within 25 km wins. A missing/out-of-range
match produces no link.
"""
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import text


MAX_CELL_LINK_DISTANCE_M = 25_000.0
PROBABLE_LINK_MAX_DISTANCE_M = 10_000.0
_METRES_PER_LATITUDE_DEGREE = 111_000.0
LTE_NEIGHBOUR_TYPES = (1, 2)
NR_NEIGHBOUR_TYPES = (1000, 1001, 1002)
NR_ANCHOR_TYPE = 199

# 0.117.0 BC3 — Mapping 3GPP EARFCN LTE → bande MHz (match
# cell_ref.band_mhz : 700/800/900/1400/1800/2100/2600/3500). Dérivé
# directement des plages 3GPP B1/B3/B7/B8/B20/B28/B32. Utilisé par le
# fallback "probable" sur la cellule serving quand le référentiel n'a
# pas d'EARFCN exact pour cette porteuse.
_LTE_EARFCN_RANGES: list[tuple[int, int, int]] = [
    (0, 599, 2100),      # B1 : 2110-2170 MHz downlink
    (1200, 1949, 1800),  # B3
    (2750, 3449, 2600),  # B7
    (3450, 3799, 900),   # B8
    (6150, 6449, 800),   # B20
    (9210, 9659, 700),   # B28
    (9770, 9869, 1500),  # B32 (SDL)
]


def _lte_earfcn_to_band_mhz(earfcn: int | None) -> int | None:
    """Band MHz autoritaire pour un EARFCN LTE donné, ou None hors plage."""
    if earfcn is None:
        return None
    try:
        e = int(earfcn)
    except (TypeError, ValueError):
        return None
    for lo, hi, band in _LTE_EARFCN_RANGES:
        if lo <= e <= hi:
            return band
    return None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance, deterministic and independent of PostGIS."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 6_371_008.8 * 2 * asin(sqrt(a))


def _within_distance_box(point: dict, ref) -> bool:
    """Cheap conservative box before the exact great-circle distance.

    ``candidate_count`` still describes every radio-identity candidate; the
    box only avoids thousands of trigonometric calculations for sites that
    cannot possibly be inside the declared 25 km proof radius.
    """
    latitude_delta = MAX_CELL_LINK_DISTANCE_M / _METRES_PER_LATITUDE_DEGREE
    if abs(float(ref["lat"]) - float(point["lat"])) > latitude_delta:
        return False
    edge_latitude = min(89.9, abs(float(point["lat"])) + latitude_delta)
    longitude_scale = max(cos(radians(edge_latitude)), 1e-6)
    longitude_delta = latitude_delta / longitude_scale
    return abs(float(ref["lng"]) - float(point["lng"])) <= longitude_delta


def enrich_radio_links(db, project_id: str, capture_id: str, map_points: list[dict]) -> None:
    """Mutate map points with optional proven links, scoped to one capture."""
    if not map_points:
        return
    points_by_seq: dict[int, list[dict]] = defaultdict(list)
    for point in map_points:
        points_by_seq[int(point["seq"])].append(point)
        point.setdefault("neighbour_links", [])
        point.setdefault("nr_anchor_link", None)

    candidate_identities = list(db.execute(text("""
        SELECT DISTINCT system,cell_type,cell_arfcn,cell_pci
        FROM nmf_cell_identity
        WHERE project_id=:pid AND capture_id=:cap AND event_code='CELLMEAS'
          AND cell_arfcn IS NOT NULL AND cell_pci IS NOT NULL
          AND ((system=7 AND cell_type=ANY(:lte_types))
            OR (system=9 AND cell_type=ANY(:nr_types)))
        ORDER BY system,cell_type,cell_arfcn,cell_pci
    """), {
        "pid": project_id,
        "cap": capture_id,
        "lte_types": list(LTE_NEIGHBOUR_TYPES),
        "nr_types": [*NR_NEIGHBOUR_TYPES, NR_ANCHOR_TYPE],
    }).mappings())
    points_with_second=[p for p in map_points if p.get("_second") is not None]
    wanted = sorted({
        (int(r["system"]), int(r["cell_arfcn"]), int(r["cell_pci"]))
        for r in candidate_identities
    })
    if not wanted:
        for point in map_points:
            point.pop("_second",None)
        return
    point_latitudes = [float(point["lat"]) for point in map_points]
    point_longitudes = [float(point["lng"]) for point in map_points]
    latitude_delta = MAX_CELL_LINK_DISTANCE_M / _METRES_PER_LATITUDE_DEGREE
    edge_latitude = min(89.9, max(abs(min(point_latitudes)), abs(max(point_latitudes)))
                        + latitude_delta)
    longitude_delta = latitude_delta / max(cos(radians(edge_latitude)), 1e-6)
    refs = list(db.execute(text("""
        WITH wanted AS (
          SELECT * FROM unnest(
            CAST(:systems AS smallint[]),CAST(:arfcns AS integer[]),
            CAST(:pcis AS integer[])
          ) AS w(system,arfcn,pci)
        ), matching AS (
          SELECT w.system,w.arfcn,w.pci,w.arfcn AS reference_channel,
                 r.id AS cell_ref_id,r.site_id,r.site_name,
                 ST_Y(r.geom) AS lat,ST_X(r.geom) AS lng
          FROM wanted w
          JOIN cell_ref r ON w.system=7 AND r.earfcn=w.arfcn AND r.pci=w.pci
          WHERE r.geom IS NOT NULL
          UNION ALL
          SELECT w.system,w.arfcn,w.pci,w.arfcn AS reference_channel,
                 r.id AS cell_ref_id,r.site_id,r.site_name,
                 ST_Y(r.geom) AS lat,ST_X(r.geom) AS lng
          FROM wanted w
          JOIN cell_ref r ON w.system=9 AND r.nr_arfcn=w.arfcn AND r.pci=w.pci
          WHERE r.geom IS NOT NULL
        )
        SELECT * FROM matching
        WHERE lat BETWEEN :min_lat AND :max_lat
          AND lng BETWEEN :min_lng AND :max_lng
        ORDER BY system,arfcn,pci,cell_ref_id
    """), {
        "systems": [v[0] for v in wanted],
        "arfcns": [v[1] for v in wanted],
        "pcis": [v[2] for v in wanted],
        "min_lat": min(point_latitudes) - latitude_delta,
        "max_lat": max(point_latitudes) + latitude_delta,
        "min_lng": min(point_longitudes) - longitude_delta,
        "max_lng": max(point_longitudes) + longitude_delta,
    }).mappings())
    candidate_counts = {}
    if refs:
        count_rows = list(db.execute(text("""
            WITH wanted AS (
              SELECT * FROM unnest(
                CAST(:systems AS smallint[]),CAST(:arfcns AS integer[]),
                CAST(:pcis AS integer[])
              ) AS w(system,arfcn,pci)
            ), matching AS (
              SELECT w.system,w.arfcn,w.pci,r.id
              FROM wanted w
              JOIN cell_ref r ON w.system=7 AND r.earfcn=w.arfcn AND r.pci=w.pci
              WHERE r.geom IS NOT NULL
              UNION ALL
              SELECT w.system,w.arfcn,w.pci,r.id
              FROM wanted w
              JOIN cell_ref r ON w.system=9 AND r.nr_arfcn=w.arfcn AND r.pci=w.pci
              WHERE r.geom IS NOT NULL
            )
            SELECT system,arfcn,pci,COUNT(*)::int AS n
            FROM matching
            GROUP BY system,arfcn,pci
        """), {
            "systems": [v[0] for v in wanted],
            "arfcns": [v[1] for v in wanted],
            "pcis": [v[2] for v in wanted],
        }).mappings())
        candidate_counts = {
            (int(row["system"]), int(row["arfcn"]), int(row["pci"])): int(row["n"])
            for row in count_rows if "n" in row
        }
    refs_by_identity: dict[tuple[int, int, int], list] = defaultdict(list)
    for ref in refs:
        key=(int(ref["system"]), int(ref["arfcn"]), int(ref["pci"]))
        item=dict(ref)
        item["candidate_count"]=candidate_counts.get(key)
        refs_by_identity[key].append(item)

    if not refs_by_identity:
        for point in map_points:
            point.pop("_second",None)
        return

    # Fetch per-seq identities only when at least one reference cell lies
    # within the capture's conservative 25 km bounding box.
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

    seen: dict[int, set[tuple[int, int, int, int]]] = defaultdict(set)
    for identity in identities:
        seq = int(identity["seq"])
        system = int(identity["system"])
        arfcn = int(identity["cell_arfcn"])
        pci = int(identity["cell_pci"])
        cell_type = int(identity["cell_type"])
        reference_channel = arfcn
        identity_key = (system, cell_type, arfcn, pci)
        if identity_key in seen[seq]:
            continue
        seen[seq].add(identity_key)
        candidates = refs_by_identity.get((system, arfcn, pci), [])
        for point in points_by_seq[seq]:
            ranked = sorted(
                ((_distance_m(point["lat"], point["lng"], ref["lat"], ref["lng"]), ref)
                 for ref in candidates if _within_distance_box(point, ref)),
                key=lambda item: (item[0], item[1]["cell_ref_id"]),
            )
            if not ranked or ranked[0][0] > MAX_CELL_LINK_DISTANCE_M:
                continue
            distance, ref = ranked[0]
            candidate_count = int(ref.get("candidate_count") or len(candidates))
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
                "candidate_count": candidate_count,
                "confidence": ("radio_arfcn_pci_unique" if candidate_count == 1
                               else "radio_arfcn_pci_nearest_within_25000m"),
            }
            if system == 9 and cell_type == NR_ANCHOR_TYPE:
                # EN-DC is proven only when this point also has a proven LTE
                # serving cell.  A lone NR PSCell is not enough to infer a link.
                if point.get("serving_cell_ref_id"):
                    point["nr_anchor_link"] = link
            else:
                point["neighbour_links"].append(link)
    for point in map_points:
        point.pop("_second", None)
    # 0.117.0 BC3 — Marque les liens serving existants comme 'earfcn_pci / proven'.
    for point in map_points:
        if point.get("serving_cell_ref_id"):
            point.setdefault("link_method", "earfcn_pci")
            point.setdefault("confidence", "proven")


def enrich_probable_serving_links(
    db, project_id: str, capture_id: str, map_points: list[dict]
) -> None:
    """Fallback 'probable' pour la cellule serving quand le référentiel
    n'a pas d'EARFCN exact ou de PCI pour la zone (cas Hénin-Beaumont /
    Test_6). Pour chaque point sans serving_cell_ref_id (= pas prouvé),
    récupère (cell_ch, cell_pci) de la PCell (cell_index=1003) sur
    la seconde du point, dérive band_mhz depuis cell_ch, cherche le
    cell_ref le plus proche à distance <= 10 km avec band_mhz égal et
    pci optionnel ; pose les champs probable_serving_* avec distance
    et confidence='probable'. Jamais présenté comme prouvé.
    """
    if not map_points:
        return
    # 1. Récupère (seq → cell_ch, cell_pci) pour PCell (cell_index=1003)
    rows = db.execute(text("""
        SELECT seq_first AS seq,
               MAX(CASE WHEN metric_code='cell_ch'  THEN value END) AS cell_ch,
               MAX(CASE WHEN metric_code='cell_pci' THEN value END) AS cell_pci
        FROM nmf_cell_second
        WHERE project_id=:pid AND capture_id=:cap AND cell_index=1003
          AND metric_code IN ('cell_ch','cell_pci')
        GROUP BY seq_first
    """), {"pid": project_id, "cap": capture_id}).mappings().all()
    pcell_by_seq = {
        int(r["seq"]): (
            int(r["cell_ch"]) if r["cell_ch"] is not None else None,
            int(r["cell_pci"]) if r["cell_pci"] is not None else None,
        )
        for r in rows
    }
    if not pcell_by_seq:
        return
    # 2. Pour chaque point sans serving, dérive bande + cherche cell_ref proche
    #    par bande+pci (prioritaire) puis bande seulement.
    unlinked = [p for p in map_points if not p.get("serving_cell_ref_id")]
    if not unlinked:
        return
    # Précharge cell_ref par (band_mhz) dans la bbox élargie des points
    lats = [float(p["lat"]) for p in unlinked]
    lngs = [float(p["lng"]) for p in unlinked]
    deg_lat = PROBABLE_LINK_MAX_DISTANCE_M / _METRES_PER_LATITUDE_DEGREE
    deg_lng = deg_lat / max(cos(radians(sum(lats) / len(lats))), 1e-6)
    refs_by_band_pci: dict[tuple[int, int], list[dict]] = defaultdict(list)
    refs_by_band: dict[int, list[dict]] = defaultdict(list)
    for r in db.execute(text("""
        SELECT id, band_mhz, pci, site_id, site_name,
               ST_Y(geom) AS lat, ST_X(geom) AS lng
        FROM cell_ref
        WHERE geom IS NOT NULL AND band_mhz IS NOT NULL
          AND ST_Y(geom) BETWEEN :lat_min AND :lat_max
          AND ST_X(geom) BETWEEN :lng_min AND :lng_max
    """), {
        "lat_min": min(lats) - deg_lat, "lat_max": max(lats) + deg_lat,
        "lng_min": min(lngs) - deg_lng, "lng_max": max(lngs) + deg_lng,
    }).mappings().all():
        ref = {k: r[k] for k in ("id", "band_mhz", "pci", "site_id",
                                  "site_name", "lat", "lng")}
        band_mhz = int(ref["band_mhz"])
        pci = int(ref["pci"]) if ref["pci"] is not None else None
        if pci is not None:
            refs_by_band_pci[(band_mhz, pci)].append(ref)
        refs_by_band[band_mhz].append(ref)

    for point in unlinked:
        seq = int(point["seq"])
        pcell = pcell_by_seq.get(seq)
        if not pcell:
            continue
        ch, pci = pcell
        band_mhz = _lte_earfcn_to_band_mhz(ch)
        if band_mhz is None:
            continue
        # Candidats : band+pci (plus spécifique) puis band seul
        candidates = (refs_by_band_pci.get((band_mhz, pci), [])
                      if pci is not None else [])
        used_fallback_band_only = False
        if not candidates:
            candidates = refs_by_band.get(band_mhz, [])
            used_fallback_band_only = True
        if not candidates:
            continue
        p_lat = float(point["lat"])
        p_lng = float(point["lng"])
        best = None
        best_d = PROBABLE_LINK_MAX_DISTANCE_M
        for ref in candidates:
            d = _distance_m(p_lat, p_lng, float(ref["lat"]), float(ref["lng"]))
            if d < best_d:
                best = ref
                best_d = d
        if best is None:
            continue
        point["probable_serving_cell_ref_id"] = best["id"]
        point["probable_serving_site_id"] = best["site_id"]
        point["probable_serving_site_name"] = best["site_name"]
        point["probable_serving_cell_lat"] = float(best["lat"])
        point["probable_serving_cell_lng"] = float(best["lng"])
        point["probable_serving_distance_m"] = round(best_d, 1)
        point["probable_serving_band_mhz"] = band_mhz
        point["probable_serving_pci"] = pci
        point["link_method"] = "band_proximity" + ("_pci" if not used_fallback_band_only else "")
        point["confidence"] = "probable"
        point["probable_link_max_distance_m"] = PROBABLE_LINK_MAX_DISTANCE_M
