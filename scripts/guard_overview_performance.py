"""Offline guard only: TEST observations, no DB connection or source writes."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import overview
from app.schemas.common import FilterContext, Project

old = {}
exec(compile(subprocess.check_output(["git", "show", "b4276ec:app/services/overview.py"], text=True),
             "baseline_overview", "exec"), old)
project = Project(id="TEST-PERF", name="TEST-PERF", geography="TEST", center=(0, 0),
    operators=["Orange", "SFR", "Bouygues", "Free"], technologies=["LTE", "NR"],
    services=["Data"], bands=["TEST-BAND"], departements=["TEST"],
    periodStart="TEST", periodEnd="TEST", captures=0, importedAt="TEST", status="ready")
overview._project_schema = lambda p: project
old["_project_schema"] = lambda p: project

class DB:
    def __init__(self, points): self.points = points
    def get(self, *args): return project
    def query(self, *fields):
        self.fields = fields
        return self
    def filter(self, *args): return self
    def all(self): return self.points

def points(n):
    return [SimpleNamespace(id=f"TEST-{i}", lat=None if i % 5 == 0 else 0.,
        lng=None if i % 5 == 0 else 0., operator=project.operators[i % 4],
        tech=["LTE", "NR", "EN-DC"][i % 3], service=None, band=None, dep=None, site=None,
        ts=f"TEST{i % 1000:06d}", dl=None if i % 7 == 0 else float(i % 20),
        rsrp=-float(i % 10), sinr=0., latency=None)
        for i in range(n)]
results = []
for n in [0, 1, 100, 10000]:
    db = DB(points(n)); filters = FilterContext(project=project.id)
    start=time.perf_counter(); before=old["compute_overview"](db, filters).model_dump()
    old_ms=1000*(time.perf_counter()-start)
    start=time.perf_counter(); after=overview.compute_overview(db, filters).model_dump()
    new_ms=1000*(time.perf_counter()-start)
    assert before == after, f"Population/result mismatch at {n}"
    assert len(db.fields)==14, "ORM entity materialization must not return"
    assert len(after["points"])==n
    results.append({"test_rows":n,"old_ms":round(old_ms,2),"new_ms":round(new_ms,2),"parity":"PASS"})
for metric in ["dl", "rsrp", "sinr", "latency"]:
    db=DB(points(100))
    f=FilterContext(project=project.id, metric=metric)
    assert old["compute_overview"](db,f).model_dump()==overview.compute_overview(db,f).model_dump()
print(json.dumps({"offline_only":True,"results":results,"all_metrics_parity":"PASS",
                  "null_coordinates_and_labels_preserved":"PASS"},indent=2))

# Exercise the real endpoint response serialization without a DB or HTTP writes.
import gzip
from starlette.requests import Request
from app.routes import projects
expected = overview.compute_overview(DB(points(100)), FilterContext(project=project.id))
projects.compute_overview = lambda db, filters: expected
for encoding in ["identity", "gzip", "gzip;q=0"]:
    request = Request({"type": "http", "headers": [(b"accept-encoding", encoding.encode())]})
    response = projects.overview(project.id, request, op=None, tech=None, svc=None,
                                band=None, dep=None, metric=None, db=None)
    compressed = response.headers.get("content-encoding") == "gzip"
    assert compressed == (encoding == "gzip")
    payload = gzip.decompress(response.body) if compressed else response.body
    assert json.loads(payload) == expected.model_dump()
print("PASS: direct JSON + gzip/identity/disabled gzip preserve exact payload")
