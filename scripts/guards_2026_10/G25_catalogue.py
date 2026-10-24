"""G25 — catalogue cohérence : payload.metrics (305) ↔ payload.nodes
(≈884). Chaque metric_code dans metrics doit référencer un nœud leaf
sélectionnable qui l'expose (par matching selection).
"""
import sys, json
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT project_id, payload FROM metrics_catalog_cache"
        )).all()
        failures = []
        for pid, payload in rows:
            if isinstance(payload, str):
                payload = json.loads(payload)
            metrics = payload.get("metrics", [])
            nodes = payload.get("nodes", [])
            leaf_selections = {
                n.get("selection") for n in nodes
                if n.get("node_type") == "leaf" and n.get("selectable")
            }
            # Chaque metric.code (ou binding équivalent) doit correspondre à
            # au moins un leaf.selection. On accepte le match par préfixe
            # (metric_code@cell) → selection commence par metric_code.
            orphans = []
            for m in metrics:
                code = m.get("code") or m.get("selection") or ""
                if not any(sel and (sel == code or sel.startswith(code + "@")) for sel in leaf_selections):
                    orphans.append(code)
            if orphans:
                failures.append((pid, orphans[:5], len(orphans)))
            print(f"G25 pid={pid} metrics={len(metrics)} nodes={len(nodes)} leaves={len(leaf_selections)} orphans={len(orphans)}")
        verdict = "PASS" if not failures else "FAIL"
        print(f"G25_VERDICT {verdict} failed_projects={len(failures)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
