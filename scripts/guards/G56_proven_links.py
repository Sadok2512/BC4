#!/usr/bin/env python3
"""G56 — fail closed when serving-link confidence disappears from map points."""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_PROJECT = "43e81a34a073"
DEFAULT_PROVEN_CAPTURE = "ecffb18dbd7f"
DEFAULT_PROBABLE_CAPTURE = "a4b0c321c52e"
DEFAULT_CODE = "cell_rsrp@lte-type-0"
EXPECTED_PROVEN = 199
MIN_PROBABLE = 4_435


def _fetch_map(base_url: str, token: str, project: str, capture: str) -> dict:
    query = urlencode({"capture_id": capture, "codes": DEFAULT_CODE})
    url = (
        f"{base_url.rstrip('/')}/projects/{quote(project, safe='')}/metrics/map?{query}"
    )
    request = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    try:
        with urlopen(request, timeout=60) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read(200).decode("utf-8", errors="replace")
        raise RuntimeError(f"http_status={exc.code} detail={detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"request_failed={type(exc).__name__}:{exc}") from exc
    if status != 200:
        raise RuntimeError(f"http_status={status}")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"invalid_json={exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("map_points"), list):
        raise RuntimeError("invalid_contract=map_points_not_list")
    return payload


def _run(args) -> int:
    try:
        proven_payload = _fetch_map(
            args.base_url, args.token, args.project, args.proven_capture
        )
        probable_payload = _fetch_map(
            args.base_url, args.token, args.project, args.probable_capture
        )
    except RuntimeError as exc:
        print(f"G56 VERDICT=FAIL reason=map_unavailable detail={exc}")
        return 1

    proven_points = proven_payload["map_points"]
    probable_points = probable_payload["map_points"]
    proven = sum(
        point.get("confidence") == "proven"
        and point.get("link_method") == "earfcn_pci"
        for point in proven_points
    )
    probable = sum(
        point.get("confidence") == "probable"
        and bool(point.get("probable_serving_cell_ref_id"))
        for point in probable_points
    )
    print(
        "G56 content "
        f"project={args.project} proven_capture={args.proven_capture} "
        f"proven_points={len(proven_points)} proven_marked={proven} "
        f"probable_capture={args.probable_capture} "
        f"probable_points={len(probable_points)} probable_serving={probable}"
    )
    if len(proven_points) != EXPECTED_PROVEN or proven != EXPECTED_PROVEN:
        print(
            "G56 VERDICT=FAIL reason=proven_serving_regression "
            f"expected={EXPECTED_PROVEN} points={len(proven_points)} marked={proven}"
        )
        return 1
    if probable < MIN_PROBABLE:
        print(
            "G56 VERDICT=FAIL reason=probable_serving_regression "
            f"minimum={MIN_PROBABLE} actual={probable}"
        )
        return 1
    print("G56 VERDICT=PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("G56_BASE_URL"))
    parser.add_argument("--token", default=os.environ.get("G51_TOKEN"))
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--proven-capture", default=DEFAULT_PROVEN_CAPTURE)
    parser.add_argument("--probable-capture", default=DEFAULT_PROBABLE_CAPTURE)
    args = parser.parse_args(argv)
    if not args.base_url:
        print("G56 VERDICT=FAIL reason=missing_base_url")
        return 2
    if not args.token:
        print("G56 VERDICT=FAIL reason=missing_token")
        return 2
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
