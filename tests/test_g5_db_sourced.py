"""G5: no hardcoded values in handlers — every number comes from the DB.

Two layers:
1. Repo scan: route files must not define numeric constants that could leak
   into responses (allowlist a small, obvious set).
2. End-to-end: for the KPI RRC summary endpoint, cross-check the value
   against the row stored in `kpi_rrc_summary`. If the handler ever drifts
   to hardcoded data, this breaks.
"""

from __future__ import annotations

import pathlib
import re

from sqlalchemy import text

from app.db import SessionLocal
from tests.conftest import PARIS

ROUTES_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "routes"

# Numeric data literals in handler code are forbidden. HTTP status codes are
# allowed (they're not data). String literals are stripped before scanning —
# version strings, timezones ("+00:00", "Z"), etc. are not data values.
_HTTP_CODES = {200, 201, 204, 400, 401, 403, 404, 409, 413, 422, 500, 501, 502}
_STRIP_STRINGS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'')
_NUM_LITERAL = re.compile(r"(?<![A-Za-z_.])(\d+\.\d+|\d{2,})(?![A-Za-z_.])")


def test_routes_have_no_data_literals():
    offenders: list[tuple[str, int, str]] = []
    for py in ROUTES_DIR.glob("*.py"):
        inside_doc = False
        for lineno, line in enumerate(py.read_text().splitlines(), start=1):
            s = line.strip()
            if s.startswith("#"):
                continue
            # Toggle module/function docstrings
            if s.startswith('"""') or s.endswith('"""'):
                inside_doc = not inside_doc if s.count('"""') == 1 else inside_doc
                continue
            if inside_doc:
                continue
            scrubbed = _STRIP_STRINGS.sub("", line)
            for m in _NUM_LITERAL.finditer(scrubbed):
                v = m.group(0)
                try:
                    n = float(v) if "." in v else int(v)
                except ValueError:
                    continue
                if isinstance(n, int) and n in _HTTP_CODES:
                    continue
                offenders.append((py.name, lineno, line.rstrip()))
                break
    assert not offenders, (
        "Valeurs numériques en dur dans un handler (interdites par les règles)\n"
        + "\n".join(f"  {f}:{ln}: {src}" for f, ln, src in offenders)
    )


def test_kpi_summary_matches_db(client):
    r = client.get("/kpi/catalog")
    assert r.status_code == 200
    served = r.json()["kpi"]
    with SessionLocal() as db:
        row = db.execute(text("SELECT name, value, samples FROM kpi_rrc_summary WHERE id=1")).one()
    assert served["name"] == row.name
    assert float(served["value"]) == float(row.value)
    assert int(served["samples"]) == int(row.samples)


def test_overview_count_matches_db(client):
    r = client.get(f"/projects/{PARIS}/overview")
    assert r.status_code == 200
    body = r.json()
    served_points = len(body["points"])
    with SessionLocal() as db:
        n = db.execute(
            text("SELECT COUNT(*) FROM measurement_points WHERE project_id=:pid"),
            {"pid": PARIS},
        ).scalar()
    assert served_points == int(n), "La somme n = lignes en base (G5)"
