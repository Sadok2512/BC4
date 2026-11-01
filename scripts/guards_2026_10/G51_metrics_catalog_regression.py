#!/usr/bin/env python3
"""G51 — Non-régression /metrics/table + /metrics/series sur TOUTES les
feuilles sélectionnables de l'arbre catalogue 2.56.2.

Résout l'écart /metrics/table ValueError int('lte-type-N') /
TypeError sorted(tuple|int) qui a laissé Codex67 avec HTTP 500 dès
qu'il cliquait sur un metric non-CELLMEAS avec code `@lte-type-N`.

Pour chaque feuille sélectionnable (`metrics[].code` du
`/projects/{pid}/metrics`), lance :

- `GET /projects/{pid}/metrics/table?codes=<code>&capture_id=<cap>&group_by=operator&include_map=false&table_only=true&page=1&page_size=25`
- `GET /projects/{pid}/metrics/series?codes=<code>&capture_id=<cap>`

Plus 3 combinaisons mixtes `@int` + `@lte-type-N` pour reproduire le
TypeError.

VERDICT :
- `n_500 == 0`           → PASS
- une 500               → FAIL (exit 1)
- une 422 non déclarée  → listée dans le rapport mais pas de FAIL si
  422 est accepté par le flag `--allow-422`.

Usage sur base vivante (lecture seule) :
  python scripts/guards_2026_10/G51_metrics_catalog_regression.py \\
    --base-url http://127.0.0.1:5174/api \\
    --project 43e81a34a073 --capture a4b0c321c52e \\
    [--limit 500] [--allow-422]

Usage sur base jetable (via le runner bench) :
  G51_BASE_URL=... G51_TOKEN=... python …

Le jeton admin est obligatoire ; généré hors du garde pour que celui-ci
reste lecture pure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def _call(base_url, token, path, timeout=60):
    req = Request(base_url + path)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept-Encoding", "gzip, deflate, br")
    t0 = time.perf_counter()
    try:
        resp = urlopen(req, timeout=timeout)
        body_size = len(resp.read())
        elapsed = time.perf_counter() - t0
        return resp.status, body_size, elapsed, None
    except HTTPError as e:
        elapsed = time.perf_counter() - t0
        body = e.read()[:200].decode("utf-8", errors="replace")
        return e.code, len(body), elapsed, body
    except Exception as e:  # pragma: no cover
        return 599, 0, time.perf_counter() - t0, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("G51_BASE_URL"))
    ap.add_argument("--token", default=os.environ.get("G51_TOKEN"))
    ap.add_argument("--project", required=True)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--limit", type=int, default=None,
                    help="Max number of leaves to probe (default: all)")
    ap.add_argument(
        "--workers", type=int, default=1, choices=(1,),
        help="Strictly sequential G51; values above 1 fail before any request",
    )
    ap.add_argument("--timeout", type=int, default=120,
                    help="Per-request timeout in seconds (production baseline: 120)")
    ap.add_argument("--allow-422", action="store_true",
                    help="Treat 422 as pass (default: pass only on 200)")
    ap.add_argument("--mixed-pairs", nargs="*",
                    default=["cell_rsrp@1178,cell_rsrp@lte-type-0",
                             "cell_rsrp@1178,cell_rsrp@lte-type-1",
                             "cell_rsrp@1178,cell_rsrp@lte-type-0,cell_rsrp@lte-type-1"],
                    help="Combinaisons de codes mélangées pour reproduire le TypeError")
    args = ap.parse_args()

    if not args.base_url:
        print("G51 VERDICT=FAIL reason=missing_base_url (--base-url obligatoire)",
              file=sys.stderr)
        return 2
    if not args.token:
        print("G51 VERDICT=FAIL reason=missing_token", file=sys.stderr)
        return 2

    print(f"G51 base_url={args.base_url} project={args.project} capture={args.capture}",
          flush=True)

    status, size, elapsed, err = _call(args.base_url, args.token,
                                       f"/projects/{args.project}/metrics")
    if status != 200:
        print(f"G51 VERDICT=FAIL reason=catalog_unavailable status={status} err={err}",
              file=sys.stderr)
        return 3
    import gzip, io
    raw = urlopen(Request(args.base_url + f"/projects/{args.project}/metrics",
                          headers={"Authorization": f"Bearer {args.token}",
                                   "Accept-Encoding": "identity"})).read()
    catalog = json.loads(raw)
    leaves = [m["code"] for m in catalog.get("metrics", [])]
    print(f"G51 leaves_in_catalog={len(leaves)}", flush=True)
    if args.limit:
        leaves = leaves[: args.limit]
        print(f"G51 leaves_tested={len(leaves)} (--limit)", flush=True)

    results = Counter()
    failures = []
    accepted = {200, 422} if args.allow_422 else {200}

    def probe(code):
        table_path = (
            f"/projects/{args.project}/metrics/table"
            f"?codes={quote(code)}"
            f"&capture_id={args.capture}"
            "&group_by=operator&include_map=false&table_only=true&page=1&page_size=25"
        )
        s, sz, el, err = _call(args.base_url, args.token, table_path,
                               timeout=args.timeout)
        series_path = (
            f"/projects/{args.project}/metrics/series"
            f"?codes={quote(code)}"
            f"&capture_id={args.capture}"
        )
        s2, sz2, el2, err2 = _call(args.base_url, args.token, series_path,
                                   timeout=args.timeout)
        return code, (s, sz, el, err), (s2, sz2, el2, err2)

    # G51 is deliberately sequential.  Eight concurrent leaves retained
    # several GiB across the four Uvicorn workers and produced transport-level
    # disconnects under host pressure, while the canonical production guard
    # completed the same 1,937 leaves sequentially.  A 599 must remain a real
    # failure; do not hide it with retries or parallel replacement requests.
    for i, code in enumerate(leaves, 1):
        code, table_result, series_result = probe(code)
        s, _sz, el, err = table_result
        s2, _sz2, el2, err2 = series_result
        results[("table", s)] += 1
        if s not in accepted:
            failures.append(("table", code, s, el, err))
        results[("series", s2)] += 1
        if s2 not in accepted:
            failures.append(("series", code, s2, el2, err2))

        if i % 50 == 0 or i == len(leaves):
            print(f"  … {i}/{len(leaves)} table[200]={results[('table',200)]} "
                  f"table[422]={results[('table',422)]} table[500]={results[('table',500)]} "
                  f"series[500]={results[('series',500)]}", flush=True)

    print(f"\nG51 mixed combinations ({len(args.mixed_pairs)}):", flush=True)
    for codes in args.mixed_pairs:
        table_path = (
            f"/projects/{args.project}/metrics/table"
            f"?codes={quote(codes)}"
            f"&capture_id={args.capture}"
            "&group_by=operator&include_map=false&table_only=true&page=1&page_size=25"
        )
        s, sz, el, err = _call(args.base_url, args.token, table_path,
                               timeout=args.timeout)
        results[("mixed", s)] += 1
        print(f"  mixed codes={codes} status={s} time={el:.2f}s", flush=True)
        if s not in accepted:
            failures.append(("mixed", codes, s, el, err))

    print("\nG51 summary (by endpoint, status):")
    for key, n in sorted(results.items()):
        print(f"  {key[0]:7s} status={key[1]} count={n}")

    n_500 = sum(v for k, v in results.items() if k[1] == 500)
    n_422 = sum(v for k, v in results.items() if k[1] == 422)
    n_200 = sum(v for k, v in results.items() if k[1] == 200)
    print(f"\nG51 n_200={n_200} n_422={n_422} n_500={n_500} failures={len(failures)}")

    if failures:
        print("\nG51 top-20 failures:")
        for row in failures[:20]:
            kind, code, s, el, err = row
            err_s = (err or "")[:120]
            print(f"  {kind:7s} status={s} code={code} time={el:.2f}s err={err_s}")

    if failures:
        print("G51 VERDICT=FAIL reason=http_regression")
        return 1
    print("G51 VERDICT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
