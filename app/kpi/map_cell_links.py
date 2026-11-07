"""Proven and probable neighbour/EN-DC links for metric map points.

Neighbour identity is read at the measurement's exact ``seq`` from
``nmf_cell_identity``; PSCell is read in the same capture-second because the
LTE and NR CELLMEAS records have distinct seq values. Proven matches use the
exact channel plus PCI. When that identity is absent from the reference,
probable matches use the measured channel's band, PCI when represented, and
the closest site within 10 km. Probable links are explicitly labelled and
never replace proven links.
"""
from collections import defaultdict
import logging
from math import asin, cos, radians, sin, sqrt
import time

from sqlalchemy import text


log = logging.getLogger(__name__)


MAX_CELL_LINK_DISTANCE_M = 25_000.0
PROBABLE_LINK_MAX_DISTANCE_M = 10_000.0
_METRES_PER_LATITUDE_DEGREE = 111_000.0
LTE_NEIGHBOUR_TYPES = (1, 2)
NR_NEIGHBOUR_TYPES = (1000, 1001, 1002)
NR_ANCHOR_TYPE = 199
MAX_NEIGHBOUR_LINKS_PER_POINT = 1


def metric_serving_identity(metric: dict) -> tuple[int | None, str | None]:
    """Map documented MAC serving roles to CELLMEAS identity enums."""
    selector = metric.get("cell_type_filter") or {}
    if metric.get("event") not in {"MACRATE", "MACRATEU"}:
        return None, None
    if selector.get("system") != 7:
        return None, None
    raw = selector.get("raw_cell_type")
    if not isinstance(raw, int) or raw < 0 or raw > 4:
        return None, None
    return (0, "PCell") if raw == 0 else (raw + 9, f"SCell {raw}")

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


# NR bands represented by the current cell-reference vocabulary. Some 3GPP
# NR-ARFCN ranges overlap; returning every compatible MHz bucket lets the
# geographical match disambiguate them while keeping confidence="probable".
_NR_ARFCN_RANGES: list[tuple[int, int, int]] = [
    (151600, 160600, 700),    # n28
    (158200, 164200, 800),    # n20
    (185000, 192000, 900),    # n8
    (285400, 303400, 1400),   # n75/n76
    (361000, 376000, 1800),   # n3
    (422000, 434000, 2100),   # n1
    (514000, 538000, 2600),   # n38/n7
    (620000, 653333, 3500),   # n78
    (2016667, 2070832, 26000),  # n258
]


def _nr_arfcn_to_band_mhz(nr_arfcn: int | None) -> tuple[int, ...]:
    if nr_arfcn is None:
        return ()
    try:
        value = int(nr_arfcn)
    except (TypeError, ValueError):
        return ()
    return tuple(band for low, high, band in _NR_ARFCN_RANGES if low <= value <= high)


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance, deterministic and independent of PostGIS."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 6_371_008.8 * 2 * asin(sqrt(a))


def _unit_xyz(lat: float, lng: float) -> tuple[float, float, float]:
    latitude = radians(lat)
    longitude = radians(lng)
    scale = cos(latitude)
    return scale * cos(longitude), scale * sin(longitude), sin(latitude)


class _ReferenceTree:
    """Small deterministic 3-D k-d tree; chord and great-circle order agree."""

    def __init__(self, refs: list[dict]):
        points = [(_unit_xyz(float(ref["lat"]), float(ref["lng"])), ref) for ref in refs]
        self.count = len(points)
        self.root = self._build(points, 0)

    @classmethod
    def _build(cls, points: list, depth: int):
        if not points:
            return None
        axis = depth % 3
        points.sort(key=lambda item: (item[0][axis], str(item[1]["id"])))
        middle = len(points) // 2
        return (
            points[middle][0], points[middle][1], axis,
            cls._build(points[:middle], depth + 1),
            cls._build(points[middle + 1:], depth + 1),
        )

    def nearest(self, lat: float, lng: float) -> tuple[dict | None, float]:
        target = _unit_xyz(lat, lng)
        best_ref = None
        best_squared = float("inf")

        def visit(node) -> None:
            nonlocal best_ref, best_squared
            if node is None:
                return
            xyz, ref, axis, left, right = node
            squared = sum((xyz[i] - target[i]) ** 2 for i in range(3))
            if best_ref is None or (squared, str(ref["id"])) < (
                best_squared, str(best_ref["id"])
            ):
                best_ref = ref
                best_squared = squared
            delta = target[axis] - xyz[axis]
            near, far = (left, right) if delta < 0 else (right, left)
            visit(near)
            if delta * delta <= best_squared:
                visit(far)

        visit(self.root)
        if best_ref is None:
            return None, PROBABLE_LINK_MAX_DISTANCE_M
        return best_ref, _distance_m(
            lat, lng, float(best_ref["lat"]), float(best_ref["lng"])
        )


class _ReferenceTrees:
    def __init__(self, groups: dict[tuple, list[dict]]):
        self.groups = groups
        self.trees: dict[tuple, _ReferenceTree] = {}

    def get(self, key):
        tree = self.trees.get(key)
        if tree is not None:
            return tree
        refs = self.groups.get(key)
        if not refs:
            return None
        tree = _ReferenceTree(refs)
        self.trees[key] = tree
        return tree


def _reference_trees(groups: dict[tuple, list[dict]]) -> _ReferenceTrees:
    return _ReferenceTrees(groups)


class _ProbableReferenceLookup:
    def __init__(self, refs: list[dict]):
        self.count = len(refs)
        by_band: dict[tuple[int, int], list[dict]] = defaultdict(list)
        by_band_pci: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
        for ref in refs:
            system = int(ref["system"])
            band = int(ref["band_mhz"])
            by_band[(system, band)].append(ref)
            if ref["pci"] is not None:
                by_band_pci[(system, band, int(ref["pci"]))].append(ref)
        self.by_band = _reference_trees(by_band)
        self.by_band_pci = _reference_trees(by_band_pci)
        self.cache: dict[tuple[int, float, float], tuple[dict | None, float]] = {}

    def _nearest(self, tree: _ReferenceTree, lat: float, lng: float):
        key = (id(tree), lat, lng)
        result = self.cache.get(key)
        if result is None:
            result = tree.nearest(lat, lng)
            self.cache[key] = result
        return result

    def match(
        self, system: int, bands: tuple[int, ...], pci: int | None,
        lat: float, lng: float,
    ) -> tuple[dict, float, int, str, int] | None:
        ranked = []
        for band in bands:
            tree = self.by_band_pci.get((system, band, pci)) if pci is not None else None
            method = "band_proximity_pci"
            if tree is None:
                tree = self.by_band.get((system, band))
                method = "band_proximity"
            if tree is None:
                continue
            ref, distance = self._nearest(tree, lat, lng)
            if ref is not None and distance <= PROBABLE_LINK_MAX_DISTANCE_M:
                ranked.append((distance, str(ref["id"]), band, method, tree.count, ref))
        if not ranked:
            return None
        distance, _, band, method, candidate_count, ref = min(ranked)
        return ref, distance, band, method, candidate_count


def load_probable_reference_lookup(db, map_points: list[dict]) -> _ProbableReferenceLookup:
    lats = [float(point["lat"]) for point in map_points]
    lngs = [float(point["lng"]) for point in map_points]
    deg_lat = PROBABLE_LINK_MAX_DISTANCE_M / _METRES_PER_LATITUDE_DEGREE
    deg_lng = deg_lat / max(cos(radians(sum(lats) / len(lats))), 1e-6)
    refs = [dict(row) for row in db.execute(text("""
        SELECT id,band_mhz,pci,site_id,site_name,
               CASE WHEN upper(COALESCE(techno,rat)) IN ('5G','NR')
                    THEN 9 ELSE 7 END AS system,
               ST_Y(geom) AS lat,ST_X(geom) AS lng
        FROM cell_ref
        WHERE geom IS NOT NULL AND band_mhz IS NOT NULL
          AND geom && ST_MakeEnvelope(:lng_min,:lat_min,:lng_max,:lat_max,4326)
          AND ST_Y(geom) BETWEEN :lat_min AND :lat_max
          AND ST_X(geom) BETWEEN :lng_min AND :lng_max
        ORDER BY system,band_mhz,pci,id
    """), {
        "lat_min": min(lats) - deg_lat, "lat_max": max(lats) + deg_lat,
        "lng_min": min(lngs) - deg_lng, "lng_max": max(lngs) + deg_lng,
    }).mappings()]
    return _ProbableReferenceLookup(refs)


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


def preserve_proven_serving_links(map_points: list[dict]) -> None:
    """Keep the public marker invariant for every pre-resolved serving link.

    Map points may reach radio enrichment through the live path, a fresh
    materialized cache, a stale cache, or a cache with no row for that seq.
    The marker belongs to the already proven ``serving_cell_ref_id`` and must
    therefore be applied before any of those paths can return or continue.
    Existing, more specific values remain untouched.
    """
    for point in map_points:
        if point.get("serving_cell_ref_id"):
            point.setdefault("link_method", "earfcn_pci")
            point.setdefault("confidence", "proven")


def enrich_radio_links(db, project_id: str, capture_id: str, map_points: list[dict]) -> None:
    """Mutate map points with optional proven links, scoped to one capture."""
    if not map_points:
        return
    preserve_proven_serving_links(map_points)
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


def enrich_probable_serving_links(
    db, project_id: str, capture_id: str, map_points: list[dict],
    reference_lookup: _ProbableReferenceLookup | None = None,
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
        SELECT project_id,capture_id,second,seq_first AS seq,
               MAX(CASE WHEN metric_code='cell_ch'  THEN value END) AS cell_ch,
               MAX(CASE WHEN metric_code='cell_pci' THEN value END) AS cell_pci
        FROM nmf_cell_second
        WHERE project_id=:pid AND capture_id=:cap AND cell_index=1003
          AND metric_code IN ('cell_ch','cell_pci')
        GROUP BY project_id,capture_id,second,seq_first
        ORDER BY project_id,capture_id,second,seq_first
    """), {"pid": project_id, "cap": capture_id}).mappings().all()
    pcell_by_seq = {
        int(r["seq"]): (
            int(r["cell_ch"]) if r["cell_ch"] is not None else None,
            int(r["cell_pci"]) if r["cell_pci"] is not None else None,
        )
        for r in rows
    }
    pcell_by_second: dict[int, list[tuple[int, int | None, int | None]]] = defaultdict(list)
    for row in rows:
        pcell_by_second[int(row["second"])].append((
            int(row["seq"]),
            int(row["cell_ch"]) if row["cell_ch"] is not None else None,
            int(row["cell_pci"]) if row["cell_pci"] is not None else None,
        ))
    if not pcell_by_seq:
        return
    # 2. Pour chaque point sans serving, dérive bande + cherche cell_ref proche
    #    par bande+pci (prioritaire) puis bande seulement.
    unlinked = [p for p in map_points if not p.get("serving_cell_ref_id")]
    if not unlinked:
        return
    lookup = reference_lookup or load_probable_reference_lookup(db, map_points)

    for point in unlinked:
        seq = int(point["seq"])
        pcell = pcell_by_seq.get(seq)
        if pcell is None and point.get("_second") is not None:
            # Non-CELLMEAS metrics have their own seq.  Reuse only an earlier
            # PCell identity from the same capture-second; never look ahead.
            preceding = [
                candidate for candidate in pcell_by_second.get(int(point["_second"]), [])
                if candidate[0] <= seq
            ]
            if preceding:
                _, ch, pci = preceding[-1]
                pcell = (ch, pci)
        if not pcell:
            continue
        ch, pci = pcell
        band_mhz = _lte_earfcn_to_band_mhz(ch)
        if band_mhz is None:
            continue
        # Candidats : band+pci (plus spécifique) puis band seul
        p_lat = float(point["lat"])
        p_lng = float(point["lng"])
        match = lookup.match(7, (band_mhz,), pci, p_lat, p_lng)
        if match is None:
            continue
        best, best_d, _, link_method, _ = match
        point["probable_serving_cell_ref_id"] = best["id"]
        point["probable_serving_site_id"] = best["site_id"]
        point["probable_serving_site_name"] = best["site_name"]
        point["probable_serving_cell_lat"] = float(best["lat"])
        point["probable_serving_cell_lng"] = float(best["lng"])
        point["probable_serving_distance_m"] = round(best_d, 1)
        point["probable_serving_band_mhz"] = band_mhz
        point["probable_serving_pci"] = pci
        point["link_method"] = link_method
        point["confidence"] = "probable"
        point["probable_link_max_distance_m"] = PROBABLE_LINK_MAX_DISTANCE_M


def enrich_metric_role_serving_links(
    db, project_id: str, capture_id: str, map_points: list[dict],
    reference_lookup: _ProbableReferenceLookup | None = None,
) -> None:
    """Resolve LTE MAC serving roles without borrowing a PCell identity.

    MACRATE/MACRATEU encode ``0=PCell`` and ``1..4=SCell1..4``.  CELLMEAS
    encodes the corresponding identities as ``0`` and ``10..13``.  For each
    metric point we use only the latest preceding identity in the *same
    capture-second* and accept it only when that identity is unique.  The
    target remains explicitly probable because the current reference lookup
    is band/PCI/proximity based; ambiguous or absent evidence produces no
    link.
    """
    targets = [
        point for point in map_points
        if point.get("_identity_cell_type") is not None
        and point.get("_second") is not None
        and not point.get("serving_cell_ref_id")
        and not point.get("probable_serving_cell_ref_id")
    ]
    if not targets:
        return
    rows = db.execute(text("""
        WITH targets AS (
          SELECT * FROM unnest(
            CAST(:target_seqs AS integer[]),
            CAST(:seconds AS integer[]),
            CAST(:cell_types AS integer[])
          ) AS t(target_seq,second,cell_type)
        ), latest AS (
          SELECT t.target_seq,t.cell_type,MAX(i.seq) AS identity_seq
          FROM targets t
          JOIN nmf_cell_identity i
            ON i.project_id=:pid AND i.capture_id=:cap
           AND i.system=7 AND i.cell_type=t.cell_type
           AND i.seq<=t.target_seq
          JOIN nmf_event_light l
            ON l.project_id=i.project_id AND l.capture_id=i.capture_id
           AND l.seq=i.seq AND l.second=t.second
          GROUP BY t.target_seq,t.cell_type
        )
        SELECT l.target_seq,l.cell_type,
               MIN(i.cell_arfcn) AS cell_arfcn,MIN(i.cell_pci) AS cell_pci
        FROM latest l
        JOIN nmf_cell_identity i
          ON i.project_id=:pid AND i.capture_id=:cap AND i.seq=l.identity_seq
         AND i.system=7 AND i.cell_type=l.cell_type
        WHERE i.cell_arfcn IS NOT NULL AND i.cell_pci IS NOT NULL
        GROUP BY l.target_seq,l.cell_type
        HAVING COUNT(DISTINCT (i.cell_arfcn,i.cell_pci))=1
        ORDER BY l.target_seq,l.cell_type
    """), {
        "pid": project_id,
        "cap": capture_id,
        "target_seqs": [int(point["seq"]) for point in targets],
        "seconds": [int(point["_second"]) for point in targets],
        "cell_types": [int(point["_identity_cell_type"]) for point in targets],
    }).mappings()
    identity_by_seq = {
        int(row["target_seq"]): (int(row["cell_arfcn"]), int(row["cell_pci"]))
        for row in rows
    }
    if not identity_by_seq:
        return
    lookup = reference_lookup or load_probable_reference_lookup(db, map_points)
    for point in targets:
        identity = identity_by_seq.get(int(point["seq"]))
        if identity is None:
            continue
        arfcn, pci = identity
        band_mhz = _lte_earfcn_to_band_mhz(arfcn)
        if band_mhz is None:
            continue
        match = lookup.match(
            7, (band_mhz,), pci, float(point["lat"]), float(point["lng"])
        )
        if match is None:
            continue
        best, distance, _, method, _ = match
        point.update({
            "serving_cell_role": point["_cell_role"],
            "serving_cell_arfcn": arfcn,
            "serving_cell_pci": pci,
            "probable_serving_cell_ref_id": best["id"],
            "probable_serving_site_id": best["site_id"],
            "probable_serving_site_name": best["site_name"],
            "probable_serving_cell_lat": float(best["lat"]),
            "probable_serving_cell_lng": float(best["lng"]),
            "probable_serving_distance_m": round(distance, 1),
            "probable_serving_band_mhz": band_mhz,
            "probable_serving_pci": pci,
            "probable_link_max_distance_m": PROBABLE_LINK_MAX_DISTANCE_M,
            "link_method": method,
            "confidence": "probable",
        })


def enrich_probable_neighbour_nr_links(
    db,
    project_id: str,
    capture_id: str,
    map_points: list[dict],
    seconds_by_seq: dict[int, int],
    reference_lookup: _ProbableReferenceLookup | None = None,
) -> None:
    """Complete missing neighbour/NR links with bounded probable matches.

    Proven exact-channel links are immutable. LTE neighbours come from the
    point's exact seq. NR candidates (PSCell first, then NR neighbour enums)
    come from CELLMEAS records in the point's capture-second. Probable LTE
    links fill at most ``MAX_NEIGHBOUR_LINKS_PER_POINT`` slots, strongest RSRP
    first. A pre-existing proven list is never truncated.
    """
    if not map_points:
        return
    started = time.perf_counter()
    points_by_seq: dict[int, list[dict]] = defaultdict(list)
    for point in map_points:
        points_by_seq[int(point["seq"])].append(point)

    lte_rows = list(db.execute(text("""
        WITH candidates AS (
          SELECT i.seq,i.system,i.cell_type,i.cell_arfcn,i.cell_pci,i.cell_index,
                 i.cell_rsrp AS strength
          FROM nmf_cell_identity i
          WHERE i.project_id=:pid AND i.capture_id=:cap
            AND i.seq=ANY(:seqs) AND i.event_code='CELLMEAS'
            AND i.system=7 AND i.cell_type=ANY(:lte_types)
            AND i.cell_arfcn IS NOT NULL
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY seq ORDER BY strength DESC NULLS LAST,
              cell_type,cell_arfcn,cell_pci,cell_index
          ) AS rank
          FROM candidates
        )
        SELECT seq,system,cell_type,cell_arfcn,cell_pci,cell_index,strength
        FROM ranked WHERE rank<=:max_neighbours
        ORDER BY seq,rank
    """), {
        "pid": project_id,
        "cap": capture_id,
        "seqs": sorted(points_by_seq),
        "lte_types": list(LTE_NEIGHBOUR_TYPES),
        "max_neighbours": MAX_NEIGHBOUR_LINKS_PER_POINT,
    }).mappings())

    nr_rows = []
    targets = [(seq, second) for seq, second in sorted(seconds_by_seq.items())]
    if targets:
        nr_rows = list(db.execute(text("""
            WITH targets AS (
              SELECT * FROM unnest(CAST(:target_seqs AS integer[]),
                                   CAST(:seconds AS integer[]))
                AS t(target_seq,second)
            )
            , candidates AS (
              SELECT t.target_seq AS seq,i.system,i.cell_type,i.cell_arfcn,
                     i.cell_pci,i.cell_index,
                     i.cell_rsrp AS strength
              FROM targets t
              JOIN nmf_event_light l
                ON l.project_id=:pid AND l.capture_id=:cap AND l.second=t.second
               AND l.event_code='CELLMEAS'
              JOIN nmf_cell_identity i
                ON i.project_id=l.project_id AND i.capture_id=l.capture_id
               AND i.seq=l.seq AND i.event_code=l.event_code
              WHERE i.system=9 AND i.cell_type=ANY(:nr_types)
                AND i.cell_arfcn IS NOT NULL
            ), ranked AS (
              SELECT *,row_number() OVER (
                PARTITION BY seq ORDER BY (cell_type=:anchor_type) DESC,
                  strength DESC NULLS LAST,cell_type,cell_arfcn,cell_pci,cell_index
              ) AS rank
              FROM candidates
            )
            SELECT seq,system,cell_type,cell_arfcn,cell_pci,cell_index,strength
            FROM ranked WHERE rank=1
            ORDER BY seq
        """), {
            "pid": project_id,
            "cap": capture_id,
            "target_seqs": [item[0] for item in targets],
            "seconds": [item[1] for item in targets],
            "nr_types": [NR_ANCHOR_TYPE, *NR_NEIGHBOUR_TYPES],
            "anchor_type": NR_ANCHOR_TYPE,
        }).mappings())

    identities = [dict(row) for row in [*lte_rows, *nr_rows]]
    if not identities:
        return
    after_identities = time.perf_counter()
    lookup = reference_lookup or load_probable_reference_lookup(db, map_points)
    after_references = time.perf_counter()
    after_indexes = time.perf_counter()

    identities_by_seq: dict[int, list[dict]] = defaultdict(list)
    for identity in identities:
        identities_by_seq[int(identity["seq"])].append(identity)

    def strongest(identity: dict) -> tuple:
        strength = identity.get("strength")
        return (
            strength is None,
            -(float(strength) if strength is not None else -9999.0),
            int(identity["cell_type"]),
            int(identity["cell_arfcn"]),
            int(identity["cell_pci"] or -1),
        )

    def probable_link(point: dict, identity: dict) -> dict | None:
        system = int(identity["system"])
        arfcn = int(identity["cell_arfcn"])
        pci = int(identity["cell_pci"]) if identity["cell_pci"] is not None else None
        bands = ((_lte_earfcn_to_band_mhz(arfcn),) if system == 7
                 else _nr_arfcn_to_band_mhz(arfcn))
        bands = tuple(band for band in bands if band is not None)
        latitude = float(point["lat"])
        longitude = float(point["lng"])
        match = lookup.match(system, bands, pci, latitude, longitude)
        if match is None:
            return None
        ref, distance, band, method, candidate_count = match
        return {
            "system": "LTE" if system == 7 else "NR",
            "arfcn": arfcn,
            "reference_channel": arfcn,
            "pci": pci,
            "cell_type": int(identity["cell_type"]),
            "cell_ref_id": ref["id"],
            "site_id": ref["site_id"],
            "site_name": ref["site_name"],
            "lat": float(ref["lat"]),
            "lng": float(ref["lng"]),
            "distance_m": round(distance, 1),
            "max_distance_m": PROBABLE_LINK_MAX_DISTANCE_M,
            "candidate_count": candidate_count,
            "confidence": "probable",
            "link_method": method,
            "band_mhz": band,
            "measured_strength_dbm": (
                float(identity["strength"]) if identity.get("strength") is not None else None
            ),
        }

    for seq, points in points_by_seq.items():
        ordered = sorted(identities_by_seq.get(seq, []), key=strongest)
        for point in points:
            proven_keys = {
                (link["system"], int(link["arfcn"]), link.get("pci"), int(link["cell_type"]))
                for link in point.get("neighbour_links", [])
            }
            slots = max(0, MAX_NEIGHBOUR_LINKS_PER_POINT - len(point.get("neighbour_links", [])))
            for identity in (item for item in ordered if int(item["system"]) == 7):
                if slots <= 0:
                    break
                key = ("LTE", int(identity["cell_arfcn"]), identity.get("cell_pci"),
                       int(identity["cell_type"]))
                if key in proven_keys:
                    continue
                link = probable_link(point, identity)
                if link is not None:
                    point.setdefault("neighbour_links", []).append(link)
                    slots -= 1
            if point.get("nr_anchor_link") is not None:
                continue
            if not (point.get("serving_cell_ref_id") or point.get("probable_serving_cell_ref_id")):
                continue
            nr_ordered = sorted(
                (item for item in ordered if int(item["system"]) == 9),
                key=lambda item: (int(item["cell_type"]) != NR_ANCHOR_TYPE, strongest(item)),
            )
            for identity in nr_ordered:
                link = probable_link(point, identity)
                if link is not None:
                    point["nr_anchor_link"] = link
                    break
    finished = time.perf_counter()
    log.info(
        "probable neighbour/NR stages project=%s capture=%s identities=%d refs=%d "
        "identity_ms=%.3f references_ms=%.3f indexes_ms=%.3f match_ms=%.3f total_ms=%.3f",
        project_id, capture_id, len(identities), lookup.count,
        (after_identities - started) * 1000,
        (after_references - after_identities) * 1000,
        (after_indexes - after_references) * 1000,
        (finished - after_indexes) * 1000,
        (finished - started) * 1000,
    )
