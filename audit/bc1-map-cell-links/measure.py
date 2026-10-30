"""Disposable-stack HTTP proof. Required env values are never printed."""
import hashlib
import json
import os
import time

import httpx

from app.services.auth import create_token


base = os.environ["BC4_API_BASE"].rstrip("/")
project = os.environ["BC4_PROOF_PROJECT_ID"]
capture = os.environ["BC4_PROOF_CAPTURE_ID"]
user = os.environ["BC4_PROOF_USER_ID"]
token, _ = create_token(
    user_id=user, role="admin", ttl_min=30, secret=os.environ["BC4_JWT_SECRET"]
)
headers = {"Authorization": f"Bearer {token}"}
common = {"capture_id": capture, "codes": "cell_rsrp@lte-type-0", "max_points": 5000}


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


for route in ("series", "table"):
    responses = {}
    for include in (False, True):
        params = {**common, "include_map": str(include).lower()}
        if route == "table":
            params["page_size"] = 25
        started = time.perf_counter()
        response = httpx.get(
            f"{base}/projects/{project}/metrics/{route}",
            params=params,
            headers=headers,
            timeout=120,
        )
        elapsed = time.perf_counter() - started
        print(route, f"include_map={str(include).lower()}", "status", response.status_code,
              "seconds", round(elapsed, 3), "bytes", len(response.content))
        response.raise_for_status()
        responses[include] = response.json()
    stable_keys = ("series",) if route == "series" else ("columns", "rows", "series", "total_rows")
    before = {key: responses[False][key] for key in stable_keys}
    after = {key: responses[True][key] for key in stable_keys}
    print(route, "content_sha_without_map", digest(before), digest(after),
          "identical", before == after)
    points = responses[True]["map_points"]
    print(route, "map_points", len(points),
          "serving", sum(bool(p.get("serving_cell_ref_id")) for p in points),
          "neighbour_points", sum(bool(p.get("neighbour_links")) for p in points),
          "neighbour_links", sum(len(p.get("neighbour_links", [])) for p in points),
          "nr_anchor", sum(bool(p.get("nr_anchor_link")) for p in points))
