"""Chaîne complète populate_measurements (purge) + populate_measurement_points
+ populate_ecgi sur REF. Idempotent, PAS de dédoublon car purge mp
project en premier.
"""
from __future__ import annotations

import sys
import traceback

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/nmf_decoder")

from app.db import SessionLocal
from app.services.populate_measurements import populate_measurements
from app.measure.populate import populate_measurement_points
from app.measure.ecgi import populate_ecgi_for_project
from app.measure.proof import format_proof_table, run_proof

PROJECT_ID = "7e656b8c6c19"


def main() -> int:
    # Étape A : populate_measurements (purge mp project, puis crée skeleton).
    print(f"[A] populate_measurements purge+skeleton project={PROJECT_ID}", flush=True)
    with SessionLocal() as db:
        try:
            r = populate_measurements(db, PROJECT_ID, purge=True)
            print(f"[A] result={r}", flush=True)
        except Exception:
            traceback.print_exc()
            return 1

    # Étape B : populate_measurement_points (UPDATE skeleton + INSERT reste).
    print(f"[B] populate_measurement_points", flush=True)
    with SessionLocal() as db:
        try:
            r = populate_measurement_points(db, PROJECT_ID, purge=False)
            print(f"[B] updated={r['updated']} inserted={r['inserted']}", flush=True)
            print(f"[B] mismatches={r['mismatches']}", flush=True)
            print(f"[B] by_category={dict(r['by_category'])}", flush=True)
            print(f"[B] operators_file={dict(r['operators_file'])}", flush=True)
            print(f"[B] mapping={r['mapping']}", flush=True)
        except Exception:
            traceback.print_exc()
            return 2

    # Étape C : populate_ecgi (strict (capture_id, earfcn)).
    print(f"[C] populate_ecgi_for_project", flush=True)
    with SessionLocal() as db:
        try:
            er = populate_ecgi_for_project(db, PROJECT_ID)
            print(f"[C] sib1_cells={er.sib1_cells} distinct_ecgi={er.distinct_ecgi}", flush=True)
            print(f"[C] mp_total={er.mp_total} mp_with_ecgi={er.mp_with_ecgi} pct={er.mp_pct_with_ecgi:.2f}", flush=True)
            if er.warnings:
                print(f"[C] warnings={er.warnings[:5]}", flush=True)
        except Exception:
            traceback.print_exc()
            return 3

    # Étape D : table de preuves.
    print("[D] PROOF TABLE :", flush=True)
    with SessionLocal() as db:
        try:
            rows = run_proof(db, PROJECT_ID)
            print(format_proof_table(rows), flush=True)
        except Exception:
            traceback.print_exc()
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
