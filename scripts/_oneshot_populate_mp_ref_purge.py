"""Run populate_measurement_points avec purge=True + populate_ecgi.

Variante du oneshot historique : PURGE préalable de mp pour éliminer les
doublons (générés par les 2 runs purge=False en session BC1). Puis
populate_ecgi strict (ecgi_source) pour fermer la boucle ECGI.
"""
from __future__ import annotations

import sys
import traceback

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/nmf_decoder")

from app.db import SessionLocal
from app.measure.populate import populate_measurement_points
from app.measure.ecgi import populate_ecgi_for_project
from app.measure.proof import format_proof_table, run_proof

PROJECT_ID = "7e656b8c6c19"


def main() -> int:
    print(f"[mp] project={PROJECT_ID}: start (purge=True)", flush=True)
    with SessionLocal() as db:
        try:
            report = populate_measurement_points(db, PROJECT_ID, purge=True)
        except Exception:
            traceback.print_exc()
            return 1
    print(f"[mp] updated={report['updated']} inserted={report['inserted']}", flush=True)
    print(f"[mp] mismatches={report['mismatches']}", flush=True)
    print(f"[mp] by_category={dict(report['by_category'])}", flush=True)
    print(f"[mp] operators_file={dict(report['operators_file'])}", flush=True)
    print(f"[mp] mapping={report['mapping']}", flush=True)
    print()

    print("[ecgi] start", flush=True)
    with SessionLocal() as db:
        try:
            er = populate_ecgi_for_project(db, PROJECT_ID)
            print(f"[ecgi] sib1_cells={er.sib1_cells} distinct_ecgi={er.distinct_ecgi}", flush=True)
            print(f"[ecgi] mp_total={er.mp_total} mp_with_ecgi={er.mp_with_ecgi} pct={er.mp_pct_with_ecgi:.2f}", flush=True)
            if er.warnings:
                print(f"[ecgi] warnings={er.warnings}", flush=True)
        except Exception:
            traceback.print_exc()
            return 2
    print()

    print("PROOF TABLE:")
    with SessionLocal() as db:
        rows = run_proof(db, PROJECT_ID)
        print(format_proof_table(rows), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
