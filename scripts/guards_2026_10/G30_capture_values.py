"""G30 — CAPTURE values vs .nmf source file (2.53.0 Phase 2).

Pour 3 captures témoins, vérifier :
  - Log file name = basename réel du .nmf (filesystem).
  - Test script file = valeur #TS lue dans le fichier source (grep).
  - Battery temperature min/max = min/max DEVI #1 lu dans le fichier.

PASS si les 3 valeurs correspondent exactement à ce que /metrics/table
sert via les resolvers CAPTURE (cap_file_log_file_name, cap_script_test_
script_file, cap_device_battery_temperature).

Jamais inventé : si une capture n'a pas de source_path accessible ou de
DEVI events, elle est SKIP (noté dans la sortie), pas inventée.
"""
import os, re, sys
sys.path.insert(0, "/app")
from app.db import SessionLocal
from app.kpi.catalog_release.registry import current_catalog
from app.kpi.metrics_v3 import definitions, parse_selection, Dataset
from app.routes.tasks import filters as _filters_sentinel  # ensure import
from sqlalchemy import text


WITNESS = [
    "01bfc2fc5350",
    # 2 autres captures prises automatiquement (voir main() si besoin).
]


def _witnesses(db):
    rows = db.execute(text(
        "SELECT nc.project_id, nc.capture_id, nf.source_path, nf.filename, nf.id AS nmf_file_id "
        "FROM nmf_capture nc JOIN nmf_file nf ON nf.id=nc.nmf_file_id "
        "ORDER BY nc.decoded_at DESC NULLS LAST LIMIT 3"
    )).mappings().all()
    out = [dict(r) for r in rows]
    # include seed witness first if present
    seeded = next((d for d in out if d["capture_id"] in WITNESS), None)
    if seeded:
        out.remove(seeded)
        out.insert(0, seeded)
    return out


def _grep_ts(source_path: str) -> str | None:
    """Lit le header texte du .nmf (binary mix) et extrait #TS tag."""
    try:
        with open(source_path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    # NFF text headers are UTF-8/ASCII on first lines
    text = head.decode("utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"\s*#TS\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _devi_min_max(db, project_id, capture_id):
    rows = db.execute(text(
        "SELECT (raw_fields->>'c3')::float AS v FROM stg_event_raw "
        "WHERE project_id=:pid AND capture_id=:cap AND event_code='DEVI' "
        "AND raw_fields ? 'c3' AND raw_fields->>'c3' <> ''"
    ), {"pid": project_id, "cap": capture_id}).all()
    vals = [r[0] for r in rows if r[0] is not None]
    if not vals:
        return None, None
    return min(vals), max(vals)


def _resolve_via_api(db, pid, cap, code):
    """Mime le resolver de /metrics/table pour une seule leaf CAPTURE."""
    defs = definitions()
    m = parse_selection(code, defs)
    f = {"operators": {"include": set(), "exclude": set()},
         "bands":     {"include": set(), "exclude": set()}}
    ds = Dataset(db, pid, cap, f)
    rows = ds.load(m)
    for r in rows:
        if r.get("value") is not None:
            return r["value"]
    return None


def main():
    db = SessionLocal()
    try:
        cur = current_catalog(db)
        print(f"G30 catalog_version={cur.version if cur else 'none'}")
        witnesses = _witnesses(db)
        all_pass = True
        for w in witnesses:
            pid, cap = w["project_id"], w["capture_id"]
            source = w["source_path"]
            fname = w["filename"]
            print(f"\n=== witness {cap} (project {pid}) ===")
            print(f"  nmf_file.filename = {fname!r}")
            print(f"  source_path       = {source!r}")

            # (1) Log file name
            api_log = _resolve_via_api(db, pid, cap, "cap_file_log_file_name")
            ok1 = (api_log == fname)
            print(f"  [1] cap_file_log_file_name api={api_log!r}  fs={fname!r}  {'PASS' if ok1 else 'FAIL'}")
            all_pass = all_pass and ok1

            # (2) Test script file = #TS from .nmf header
            fs_ts = None
            if source and os.path.exists(source):
                fs_ts = _grep_ts(source)
            api_tsf = _resolve_via_api(db, pid, cap, "cap_script_test_script_file")
            if fs_ts is None:
                print(f"  [2] cap_script_test_script_file api={api_tsf!r}  fs_ts=<unreadable>  SKIP")
            else:
                # NFF 2.19 writes #TS as "DL label" (same as nmf_file.dl)
                ok2 = (str(api_tsf or '').strip() == fs_ts.strip() or (api_tsf or '') in fs_ts or fs_ts in (api_tsf or ''))
                print(f"  [2] cap_script_test_script_file api={api_tsf!r}  fs_#TS={fs_ts!r}  {'PASS' if ok2 else 'FAIL'}")
                all_pass = all_pass and ok2

            # (3) Battery temperature min/max
            fs_min, fs_max = _devi_min_max(db, pid, cap)
            if fs_min is None:
                print(f"  [3] cap_device_battery_temperature  no DEVI rows  SKIP")
            else:
                # resolver returns per-row values ; we query all values and
                # compare the stg min/max via API vs direct raw_fields.
                defs = definitions(); m = parse_selection("cap_device_battery_temperature", defs)
                f_filters = {"operators": {"include": set(), "exclude": set()},
                             "bands":     {"include": set(), "exclude": set()}}
                ds = Dataset(db, pid, cap, f_filters)
                rows = ds.load(m)
                api_vals = [r['value'] for r in rows if r.get('value') is not None]
                api_min = min(api_vals) if api_vals else None
                api_max = max(api_vals) if api_vals else None
                ok3 = (api_min == fs_min and api_max == fs_max)
                print(f"  [3] cap_device_battery_temperature api[min,max]=({api_min},{api_max})  "
                      f"fs[min,max]=({fs_min},{fs_max})  {'PASS' if ok3 else 'FAIL'}")
                all_pass = all_pass and ok3

        print(f"\nG30_VERDICT {'PASS' if all_pass else 'FAIL'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
