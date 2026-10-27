"""G24 — feuilles catalogue à n=0 dont le CHAMP FICHIER est non vide.

Phase 3b préalable (BC3, 2026-10-25) — version remise à zéro après
critique "mode trust = ne vérifie rien" (G24 lot 0.80.0 avait sauté la
re-count). Ici on **RECOMPTE** vraiment, depuis `nmf_event_light`, sur
un **projet témoin** par défaut : `134af70a06eb` (le plus riche en Light,
391/786 leaves selectable avec n>0 en cache).

Pour chaque leaf de la cache avec `n=0` ET `source_column` non vide :
  SELECT COUNT(*) FROM nmf_event_light
   WHERE project_id=:pid AND "<col>" IS NOT NULL;
Si la count live > 0 → false_zero (catalog mentait).

Pour éviter de scanner `nmf_event_light` N fois, on BATCH la projection
en une seule requête par chunk de 50 colonnes (COUNT FILTER WHERE col IS
NOT NULL), même technique que `app.kpi.metrics_catalog_v4._n_per_column`.

Usage (défaut = 134af70a06eb) :
  python scripts/guards_2026_10/G24_leaves.py
  python scripts/guards_2026_10/G24_leaves.py --pid <project_id>
  python scripts/guards_2026_10/G24_leaves.py --pid <pid> --limit 0  # tous
"""
import argparse, sys
from collections import defaultdict
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

CHUNK = 50


def main():
    ap = argparse.ArgumentParser()
    # --pid OBLIGATOIRE. Pas de défaut hardcodé (ex. "134af70a06eb") : après
    # reset DB, un défaut pointerait vers un projet absent et G24 ferait
    # VERDICT FAIL silencieux. Ici l'omission du flag → argparse exit=2
    # avec message clair, pas de SKIP, pas de FAIL muet.
    ap.add_argument("--pid", required=True,
                    help="project_id témoin à recompter (OBLIGATOIRE)")
    ap.add_argument("--limit", type=int, default=0,
                    help="limite de candidats re-comptés (0 = tous)")
    args = ap.parse_args()
    pid = args.pid

    db = SessionLocal()
    try:
        # 1) Stats globales par projet
        pids = [r[0] for r in db.execute(text(
            "SELECT project_id FROM metrics_catalog_cache ORDER BY project_id"
        )).all()]
        print(f"{'project_id':<20} {'reason':<36} {'leaves_total':>12} {'selectable':>11} {'n>0':>5}")
        for p in pids:
            row = db.execute(text("""
                SELECT coalesce(payload->>'reason','pre-0.80.0') AS reason,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf') AS leaves_total,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'selectable')='true') AS leaves_selectable,
                       COUNT(*) FILTER (WHERE m->>'node_type'='leaf' AND (m->>'n')::int>0) AS leaves_n_gt0
                FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
                WHERE c.project_id=:pid
                GROUP BY payload->>'reason'
            """), {"pid": p}).first()
            if row is None:
                print(f"{p:<20} empty cache")
                continue
            reason, total, selectable, n_gt0 = row
            flag = "  <= witness" if p == pid else ""
            print(f"{p:<20} {reason:<36} {total:>12} {selectable:>11} {n_gt0:>5}{flag}")

        # 2) Re-count LIVE sur le projet passé en --pid.
        print(f"\n[G24 recount] witness project={pid}")
        if pid not in pids:
            print(f"G24_VERDICT FAIL witness_pid={pid} not in metrics_catalog_cache "
                  f"(available: {pids or 'empty cache'})")
            sys.exit(1)

        candidates = db.execute(text("""
            SELECT m->>'source_column' AS col, m->>'label' AS lbl, m->>'node_id' AS nid
            FROM metrics_catalog_cache c, jsonb_array_elements(c.payload->'nodes') m
            WHERE c.project_id=:pid AND m->>'node_type'='leaf'
              AND (m->>'n')::int=0
              AND m->>'source_column' IS NOT NULL AND m->>'source_column' <> ''
        """), {"pid": pid}).all()
        if args.limit > 0:
            candidates = candidates[:args.limit]
        print(f"[G24 recount] n_candidates={len(candidates)} (leaves n=0 avec source_column non vide)")

        # Grouper par colonne (plusieurs leaves peuvent pointer la même colonne)
        col_to_rows: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for col, lbl, nid in candidates:
            if not col: continue
            if not col.replace("_", "").isalnum(): continue  # safe-guard identifier
            col_to_rows[col].append((lbl, nid))

        # 0.88.1 — Pré-filtrage par introspection schema. Les source_column
        # qui ne correspondent PAS à une colonne de nmf_event_light sont
        # ignorés (colonnes virtuelles ex. `cap_*` du resolver CAPTURE
        # Phase 2 : routées via metrics_v3_capture, pas via colonne SQL).
        # Avant 0.88.1 : UndefinedColumn PostgreSQL crashait le batch SELECT
        # → G24 exception sans ligne VERDICT → `docker exec … | tail` masquait
        # l'exit code → récap "G24 PASS implicite" muet depuis 0.84.0 CAPTURE
        # Phase 2 (commit 0046792, 2026-10-26).
        physical_cols = {r[0] for r in db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nmf_event_light'"
        )).all()}
        virtual_cols = sorted(c for c in col_to_rows if c not in physical_cols)
        for c in virtual_cols:
            col_to_rows.pop(c, None)
        if virtual_cols:
            print(f"[G24 recount] virtual_cols ignored (not in nmf_event_light schema): "
                  f"{len(virtual_cols)} — e.g. {virtual_cols[:3]}")

        # Batched COUNT par colonne
        cols = sorted(col_to_rows.keys())
        counts: dict[str, int] = {}
        for i in range(0, len(cols), CHUNK):
            chunk = cols[i:i+CHUNK]
            expr = ", ".join(
                f'COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) AS "c_{idx}"'
                for idx, c in enumerate(chunk)
            )
            sql = f"SELECT {expr} FROM nmf_event_light WHERE project_id=:pid"
            row = db.execute(text(sql), {"pid": pid}).first()
            if row is None:
                continue
            for idx, c in enumerate(chunk):
                counts[c] = int(row[idx] or 0)

        false_zeros = [(c, counts[c], col_to_rows[c])
                       for c in cols if counts.get(c, 0) > 0]
        print(f"[G24 recount] cols_recounted={len(cols)} false_zeros={len(false_zeros)}")
        for col, n_live, rows in false_zeros[:20]:
            lbl0, nid0 = rows[0]
            print(f"  FALSE_ZERO col={col} n_live={n_live} leaves_sharing_col={len(rows)}  label={lbl0}  node_id={nid0}")

        verdict = "PASS" if not false_zeros else "FAIL"
        print(f"G24_VERDICT {verdict} witness_pid={pid} "
              f"candidates_recounted={len(cols)} false_zeros={len(false_zeros)}")
        # 0.88.1 — exit non-zero sur FAIL (ou sur exception non-attrapée).
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
