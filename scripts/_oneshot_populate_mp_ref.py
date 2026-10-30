"""Run populate_measurement_points on REF_PETITE_FORET + print proof table.

Used after 0.36.0 patch to confirm the full dérivation chain works
end-to-end once stg_event.system is backfilled."""

from __future__ import annotations

import sys
import traceback

try:
    from app.db import SessionLocal
    from app.measure.populate import populate_measurement_points
    from app.measure.proof import format_proof_table, run_proof
    from app.scripts.deploy_guard import guard_bc3_deploy_lock
except ModuleNotFoundError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.db import SessionLocal
    from app.measure.populate import populate_measurement_points
    from app.measure.proof import format_proof_table, run_proof
    from app.scripts.deploy_guard import guard_bc3_deploy_lock


PROJECT_ID = "7e656b8c6c19"


def main() -> int:
    if not guard_bc3_deploy_lock(action="oneshot_populate_mp_ref"):
        return 1
    print(f"[mp] project={PROJECT_ID}: start", flush=True)
    with SessionLocal() as db:
        try:
            report = populate_measurement_points(db, PROJECT_ID, purge=False)
        except Exception:
            traceback.print_exc()
            return 1

    print(f"[mp] updated={report['updated']} inserted={report['inserted']}", flush=True)
    print(f"[mp] mismatches={report['mismatches']}", flush=True)
    print(f"[mp] by_category={dict(report['by_category'])}", flush=True)
    print(f"[mp] operators_file={dict(report['operators_file'])}", flush=True)
    print(f"[mp] mapping={report['mapping']}", flush=True)
    print()
    print("PROOF TABLE:")
    with SessionLocal() as db:
        rows = run_proof(db, PROJECT_ID)
        print(format_proof_table(rows), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
