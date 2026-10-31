#!/usr/bin/env python3
"""Audit saved `/metrics/map` responses by response content.

Usage: measure_response.py CAPTURE=FILE.json [...]
Counts only links whose content has ``confidence=probable`` and independently
recomputes every distance from the point and referenced-cell coordinates.
"""
import json
import math
import sys


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = map(math.radians, (lat1, lat2))
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6_371_008.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


examples = []
seen = set()
for argument in sys.argv[1:]:
    capture, path = argument.split("=", 1)
    with open(path, encoding="utf-8") as source:
        points = json.load(source)["map_points"]
    neighbours = []
    anchors = []
    max_delta = 0.0
    for point in points:
        if len(point.get("neighbour_links") or []) > 1:
            raise SystemExit(f"FAIL cap_exceeded capture={capture} seq={point['seq']}")
        links = [("neighbour", link) for link in point.get("neighbour_links") or []]
        if point.get("nr_anchor_link"):
            links.append(("nr", point["nr_anchor_link"]))
        for kind, link in links:
            calculated = haversine(
                point["lat"], point["lng"], link["lat"], link["lng"]
            )
            max_delta = max(max_delta, abs(calculated - link["distance_m"]))
            if link.get("confidence") != "probable":
                continue
            target = neighbours if kind == "neighbour" else anchors
            target.append((point, link, calculated))
            key = (capture, kind, link["cell_ref_id"], link["arfcn"], link.get("pci"))
            if key not in seen:
                seen.add(key)
                examples.append((capture, kind, point, link, calculated))

    def average(items):
        if not items:
            return None
        return round(sum(item[1]["distance_m"] for item in items) / len(items), 3)

    print(
        capture,
        f"response_points={len(points)}",
        f"points_probable_neighbour={sum(any(x.get('confidence') == 'probable' for x in p.get('neighbour_links') or []) for p in points)}",
        f"probable_neighbour_links={len(neighbours)}",
        f"avg_probable_neighbour_m={average(neighbours)}",
        f"points_probable_nr={len(anchors)}",
        f"avg_probable_nr_m={average(anchors)}",
        f"max_distance_recalc_delta_m={max_delta:.6f}",
        f"max_neighbours={max((len(p.get('neighbour_links') or []) for p in points), default=0)}",
    )

for index, (capture, kind, point, link, calculated) in enumerate(examples[:5], 1):
    print(
        "EXAMPLE", index, capture, kind, f"seq={point['seq']}",
        f"cell_ref={link['cell_ref_id']}", f"system={link['system']}",
        f"arfcn={link['arfcn']}", f"pci={link.get('pci')}",
        f"api_m={link['distance_m']}", f"independent_m={calculated:.3f}",
        f"delta_m={abs(calculated - link['distance_m']):.3f}",
    )
print("VERDICT=PASS")
