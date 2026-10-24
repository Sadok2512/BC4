"""G27 — events `unknown` (array non vide) ne doivent concerner que la
liste contrôlée des codes non documentés par NFF 2.19 (CMDREQ, CMDCOMP,
SCRIPT, DAA, DREQ, DCOMP, PSMI, …). Toute occurrence sur un code
documenté = fuite silencieuse à remonter.
"""
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

DOCUMENTED_OK_UNDOC = {
    "CMDREQ","CMDCOMP","SCRIPT","DAA","DREQ","DCOMP","PSMI","PSM","PSMR",
    "APPLIST","MARK","ROAM","LOCK","GAA","GAC","GAD","PAA","PAC","PAD",
    "PBA","PBC","PBD","RABA","RABC","RABD","CAA","CAC","CAD",
}

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT event_code, COUNT(*) AS n
            FROM nmf_event_light
            WHERE unknown IS NOT NULL AND array_length(unknown, 1) > 0
            GROUP BY event_code ORDER BY n DESC
        """)).all()
        leaked = [(e, n) for e, n in rows if e not in DOCUMENTED_OK_UNDOC]
        for e, n in rows:
            tag = "LEAK" if e not in DOCUMENTED_OK_UNDOC else "ok"
            print(f"G27 {tag} {e}: {n}")
        verdict = "PASS" if not leaked else "FAIL"
        print(f"G27_VERDICT {verdict} leaked_codes={len(leaked)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
