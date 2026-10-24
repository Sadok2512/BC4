"""G25 — après invalidation cache + relance, 0 orphelin métrique.

Chaque metric_row.code dans payload.metrics doit être consommable par
AU MOINS 1 leaf.selection (format `code` ou `code@cell_idx`).
"""
import json, sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT project_id, payload FROM metrics_catalog_cache ORDER BY project_id"
        )).all()
        total_orphans = 0
        for pid, payload in rows:
            if isinstance(payload, str): payload = json.loads(payload)
            metrics = payload.get("metrics", [])
            nodes = payload.get("nodes", [])
            leaf_sel = {n.get("selection") for n in nodes
                        if n.get("node_type") == "leaf" and n.get("selection")}
            # Un metric est "consommable" si au moins un leaf a selection
            # commençant par <code> (potentiellement suffixé @N).
            orphans = []
            for m in metrics:
                code = m.get("code")
                if not code: continue
                if any(sel == code or sel.startswith(code + "@") for sel in leaf_sel): continue
                orphans.append(code)
            total_orphans += len(orphans)
            print(f"G25 {pid}: metrics={len(metrics)} leaves={len(leaf_sel)} orphans={len(orphans)}"
                  + (f"  sample={orphans[:3]}" if orphans else ""))
        verdict = "PASS" if total_orphans == 0 else "FAIL"
        print(f"G25_VERDICT {verdict} total_orphans={total_orphans}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
