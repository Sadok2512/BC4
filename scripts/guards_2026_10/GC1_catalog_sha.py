"""GC1 — sha256 du catalogue courant = sha enregistré.

Lit `catalog_release` (ligne is_current), hash le JSON on-disk, compare.
PASS si équivalence. FAIL si divergence (artefact modifié hors-build).
"""
import sys
sys.path.insert(0, "/app")
from app.db import SessionLocal
from app.kpi.catalog_release.registry import current_catalog, CATALOG_DIR, sha256_file

def main() -> int:
    db = SessionLocal()
    try:
        cat = current_catalog(db)
        if cat is None:
            print("GC1 NO_CURRENT_CATALOG — catalog_release vide (bootstrap)")
            print("GC1_VERDICT FAIL")
            return 1
        path = CATALOG_DIR / f"catalog_{cat.version}.json"
        if not path.exists():
            print(f"GC1 MISSING_FILE {path}")
            print("GC1_VERDICT FAIL")
            return 1
        on_disk = sha256_file(path)
        print(f"GC1 version={cat.version} spec={cat.spec_version} decoder_min={cat.decoder_min_version}")
        print(f"GC1 db_sha={cat.sha256}")
        print(f"GC1 disk_sha={on_disk}")
        verdict = "PASS" if on_disk == cat.sha256 else "FAIL"
        print(f"GC1_VERDICT {verdict}")
        return 0 if verdict == "PASS" else 1
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
