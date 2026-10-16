"""Backfill `measurement_points` depuis `stg_measurement_raw` (0.24.0).

Utilitaire pour (re-)déclencher `populate_measurements` sur les projets
dont le staging mesure (`stg_measurement_raw`) a été rempli mais sans
que le populate ait tourné (ex. upgrade de version pendant un batch
d'ingestion). Appel idempotent.

Usage :
    docker compose exec api python scripts/backfill_measurements.py           # tous
    docker compose exec api python scripts/backfill_measurements.py <pid>...  # ciblés

Rappel : Phase 1 (mapping champ→métrique) non faite → les colonnes
métriques resteront NULL. Ce script ne fait QUE l'armature géographique.
Les projets ingérés AVANT 0.24.0 (décodeur 1.0.0) n'ont PAS de lignes
dans `stg_measurement_raw` → ce backfill ne produit rien pour eux ;
il faut ré-ingérer les NMF.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.db import SessionLocal
from app.services.populate_measurements import populate_measurements


def main(argv: list[str]) -> int:
    with SessionLocal() as db:
        if len(argv) > 1:
            project_ids = argv[1:]
        else:
            rows = db.execute(
                text(
                    "SELECT DISTINCT project_id FROM stg_measurement_raw"
                )
            ).all()
            project_ids = [r[0] for r in rows]

        if not project_ids:
            print("Aucun projet avec stg_measurement_raw non vide — rien à faire.")
            return 0

        print(f"Backfill de {len(project_ids)} projet(s) :")
        for pid in project_ids:
            report = populate_measurements(db, pid, purge=True)
            print(
                f"  {pid}: inserted={report['inserted']} "
                f"by_system={report['by_system']} "
                f"by_operator={report['by_operator']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
