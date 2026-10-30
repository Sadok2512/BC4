"""Reproducible stage profiler for the legacy include_map response."""
import json
import time

from sqlalchemy import event

from app.db import SessionLocal, engine
from app.kpi.metrics_v3 import Dataset, definitions, parse_selection
from app.routes.metrics_v3 import Analysis

PID = "43e81a34a073"
CAP = "a4b0c321c52e"
sql_timings = []


@event.listens_for(engine, "before_cursor_execute")
def before(_conn, _cursor, _statement, _parameters, context, _many):
    context._profile_started = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def after(_conn, _cursor, statement, _parameters, context, _many):
    sql_timings.append((time.perf_counter() - context._profile_started,
                        " ".join(statement.split())[:180]))


with SessionLocal() as db:
    selected = [parse_selection("cell_rsrp@lte-type-0", definitions())]
    started = time.perf_counter()
    dataset = Dataset(db, PID, CAP, {}, lean_table=False)
    after_init = time.perf_counter()
    result = dataset.response(selected, include_map=True)
    after_response = time.perf_counter()
    validated = Analysis.model_validate(result)
    after_validate = time.perf_counter()
    encoded = validated.model_dump_json()
    after_encode = time.perf_counter()

print(json.dumps({
    "dataset_init_s": round(after_init - started, 6),
    "response_s": round(after_response - after_init, 6),
    "pydantic_validate_s": round(after_validate - after_response, 6),
    "json_encode_s": round(after_encode - after_validate, 6),
    "json_bytes": len(encoded.encode()),
    "map_points": len(result["map_points"]),
    "sql_execute_s": round(sum(item[0] for item in sql_timings), 6),
    "sql": [{"seconds": round(seconds, 6), "statement": statement}
            for seconds, statement in sorted(sql_timings, reverse=True)],
}, indent=2))
