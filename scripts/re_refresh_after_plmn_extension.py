#!/usr/bin/env python3
"""One-shot (0.14.0) : re-refresh de tous les projets ingérés après
l'extension de la table PLMN (bc4-enrich 1.2.0).

Rôle
----
- rejouer `refresh_project_summary` sur chaque projet avec un ingest
  réel (`status_ingest IS NOT NULL`) et sur les projets seedés B0
  (ils ont `status_ingest = NULL` mais des captures seedés) ;
- rapporter les deltas (captures / operators) AVANT / APRÈS, projet
  par projet ;
- **idempotent** : rejouer ne change rien de plus qu'un refresh.

Garantie structurelle (fix 0.14.0 bug mirror)
---------------------------------------------
Un projet seedé B0 sans fichier NMF réellement ingéré a
`n_captures_ingest = 0`. L'ancienne garde `is not None` écrasait
`captures` à 0 au refresh. La nouvelle garde `> 0` protège les
captures seedés (Paris 2.4M, Lyon 850k, ...). Ce script le confirme.

Lancement
---------
    docker exec bc4-api-1 python /app/scripts/re_refresh_after_plmn_extension.py
    # ou en local :
    python scripts/re_refresh_after_plmn_extension.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy import select

try:
    from app.db import SessionLocal
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project
    from app.scripts.deploy_guard import guard_bc3_deploy_lock
except ModuleNotFoundError:
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from app.db import SessionLocal
    from app.ingest.nmf import refresh_project_summary
    from app.models import Project
    from app.scripts.deploy_guard import guard_bc3_deploy_lock


def _snap(p: Project) -> dict[str, Any]:
    """Instantané lisible des champs qu'on va comparer."""
    return {
        "captures": p.captures,
        "n_captures_ingest": p.n_captures_ingest,
        "operators": list(p.operators or []),
    }


def main() -> int:
    if not guard_bc3_deploy_lock(action="re_refresh_after_plmn_extension"):
        return 1
    rc = 0
    with SessionLocal() as db:
        projects = db.execute(select(Project)).scalars().all()
        for p in projects:
            before = _snap(p)
            try:
                refresh_project_summary(db, p)
            except Exception as e:  # pragma: no cover — surface honnête
                print(f"[refresh] {p.id} ({p.name}) : ERROR {e!r}", flush=True)
                rc = 1
                continue
            # refresh_project_summary commit déjà en interne — on relit
            # directement depuis l'objet (session attaché).
            after = _snap(p)
            delta = {}
            if before["captures"] != after["captures"]:
                delta["captures"] = (before["captures"], after["captures"])
            if before["operators"] != after["operators"]:
                delta["operators"] = (before["operators"], after["operators"])
            tag = "DELTA" if delta else "noop"
            print(
                f"[refresh:{tag}] {p.id} ({p.name}) "
                f"before={json.dumps(before, ensure_ascii=False)} "
                f"after={json.dumps(after, ensure_ascii=False)} "
                f"delta={json.dumps(delta, ensure_ascii=False) if delta else '{}'}",
                flush=True,
            )
    return rc


if __name__ == "__main__":
    sys.exit(main())
