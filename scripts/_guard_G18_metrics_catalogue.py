"""Manual Metrics catalogue v6 guards. Run after cache warm-up."""
import json
from sqlalchemy import text
from app.db import SessionLocal
from app.kpi.metrics_catalogue_v6 import CELLS, source_tree

PROJECTS = ("134af70a06eb", "4b7bfd50ddb6")


def expected_nodes():
    rows = []
    def visit(node, parent, order):
        key = (parent, order, node["label"])
        rows.append(key)
        for child_order, child in enumerate(node["children"]):
            visit(child, key, child_order)
    for root_order, root in enumerate(source_tree()["tree"]):
        visit(root, None, root_order)
    return rows


with SessionLocal() as db:
    results = {}
    expected = expected_nodes()
    for project_id in PROJECTS:
        payload = db.execute(
            text("SELECT payload FROM metrics_catalog_cache WHERE project_id=:pid"),
            {"pid": project_id},
        ).scalar_one()
        nodes = payload["nodes"]
        by_parent = {}
        for node in nodes:
            by_parent.setdefault(node["parent_id"], []).append(node)
        stars = [node for node in nodes if node["node_type"] == "metric" and "★" in node["label"]]
        cells = [cell for cell, _label, _index in CELLS]
        g18a = all(
            [child["cell"] for child in sorted(by_parent.get(star["node_id"], []), key=lambda row: row["order"])] == cells
            for star in stars
        )
        # node_id and parent_id are stable hashes of the exact source path; a
        # complete ordered label comparison catches any dropped/reordered node.
        def actual_rows():
            rows = []
            def visit(node, parent, order):
                key = (parent, order, node["label"])
                rows.append(key)
                for child in sorted(by_parent.get(node["node_id"], []), key=lambda row: row["order"]):
                    visit(child, key, child["order"])
            for root in sorted(by_parent.get(None, []), key=lambda row: row["order"]):
                visit(root, None, root["order"])
            return rows
        results[project_id] = {
            "G18a": g18a,
            "star_metrics": len(stars),
            "G18b": actual_rows() == expected,
            "expected_nodes": len(expected),
            "rendered_nodes": len(nodes),
        }
    txpc = db.execute(text("""WITH rows AS (
      SELECT project_id,txpc_pucch_tx_power,
        CASE WHEN format_version='2.62' THEN tokens[array_length(tokens,1)-1]
             ELSE tokens[array_length(tokens,1)] END AS cell_type
      FROM nmf_event_deep
      WHERE project_id=ANY(:projects) AND event_code='TXPC' AND system=7)
    SELECT count(*) FILTER(WHERE txpc_pucch_tx_power IS NOT NULL) AS populated,
      count(*) FILTER(WHERE txpc_pucch_tx_power IS NOT NULL AND cell_type='0') AS pcell
    FROM rows"""), {"projects": list(PROJECTS)}).mappings().one()
    results["G18c"] = {
        "pass": txpc["populated"] > 0 and txpc["populated"] == txpc["pcell"],
        "pucch_non_null": txpc["populated"],
        "cell_type_zero": txpc["pcell"],
    }
    print(json.dumps(results, indent=2))
    assert all(row["G18a"] and row["G18b"] for row in results.values() if isinstance(row, dict) and "G18a" in row)
    assert results["G18c"]["pass"]
