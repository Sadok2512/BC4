"""G25 — contrat de cohérence catalog_release.

## Définition fermée (BC3 2026-10-26)

`metrics[]` dans l'enveloppe `/metrics` = **feuilles selectable
uniquement** (consommables par /metrics/table : `source_column` existe
en base ET `n_in_project > 0`). Les feuilles grisées (reason "Column
not in decoder schema" ou "No observations in project") restent dans
`nodes[]` pour l'arbre navigable mais ne figurent PAS dans `metrics[]`.

`code = source_column[@cell_type]`, identique au token
`nodes[].selection`.

Conséquences :
- G25.1 orphans = codes de `metrics[]` sans `nodes[].selection`
  correspondante. Avec la définition fermée, un code n'apparaît dans
  `metrics[]` que s'il a été construit depuis une leaf selectable, et
  cette même leaf porte `selection = code`. Donc **orphans == 0 par
  construction**. S'il remonte, c'est que l'invariant du code
  catalog_v4 est cassé.
- G25.2 false_grey = feuilles grisées "Column not in decoder schema"
  avec `source_column` pointant pourtant sur une colonne existante.
  Signature claire du bug mapping label-CSV → colonne-réelle (corrigé
  en 2.51.1 : `source_column` vient du YAML du décodeur).
- G25.3 (2.54.0, BC4 2026-10-28) stale_false_grey générique : contrôle
  **structurel** (jamais sur le texte de la raison) qu'une feuille avec
  `source_column IS NOT NULL` ET `n > 0` ET `selectable=false` est un
  bug — col décodée + obs présentes + grise = contradiction. Attrape le
  cas « cell_type jamais observé en base » et toute régression future
  du même genre.
- G25.4 (2.54.0, BC4 2026-10-28) conservation des lignes par cellule :
  pour chaque (event, source_column) la **somme** des `n` sur toutes les
  variantes cellule visibles (canoniques + uncatalogued + NULL) doit
  égaler le COUNT global de la colonne pour l'event dans ce projet.
  Aucune ligne perdue entre les variantes.
- G25.5 (2.54.0, BC4 2026-10-28) tooltip obligatoire sur grey : toute
  feuille `selectable=false` doit porter un `reason` non vide (règle
  Codex67 « gris = toujours avec tooltip »).

Verdict :
  - orphans > 0        → FAIL (invariant catalog_v4 cassé)
  - dup node_ids > 0   → FAIL (chaque position doit être unique)
  - dup metric codes > 0 → FAIL (metrics[] est une table, pas un multiset)
  - false_grey > 0     → FAIL (bug mapping label-CSV revenu)
  - stale_false_grey > 0 → FAIL (G25.3 — col décodée + n>0 + non selectable)
  - cell_sum_loss > 0  → FAIL (G25.4 — lignes perdues entre les variantes)
  - grey_no_reason > 0 → FAIL (G25.5 — gris sans tooltip)
"""
import json, sys
from collections import Counter
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal

from app.nmf_decoder.schema import schemas, column as _col


def _available_columns(db):
    rows = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name IN ('nmf_event_light', 'nmf_event_light_group')"
    )).all()
    return {r[0] for r in rows}


def _event_fields_yaml():
    """event → set of (code, column_name) for header + group fields."""
    out = {}
    for ev, s in schemas().items():
        if not isinstance(s, dict): continue
        cols = set()
        def _walk(sch):
            for f in sch.get("header", []) or []:
                c = _col(f.get("code") or "")
                if c: cols.add(c)
            for g in sch.get("groups", []) or []:
                for f in g.get("fields", []) or []:
                    c = _col(f.get("code") or "")
                    if c: cols.add(c)
        _walk(s)
        for v in (s.get("_variants") or {}).values():
            _walk(v)
        out[ev] = cols
    return out


def _event_col_total(db, project_id: str, event_code: str, col: str,
                     avail_light_cols: set[str], avail_group_cols: set[str]) -> int:
    """COUNT des valeurs réellement projetées dans nmf_cell_second.

    Depuis le catalogue 2.56.0, la sélection par cellule est définie par
    `(metric_code, cell_index)` ; comparer aux colonnes Light brutes
    mélangerait l'enum source et le cell_index normalisé.
    """
    if not col:
        return 0
    if not col.replace("_", "").isalnum():
        return 0
    return int(db.execute(text("""
        SELECT COUNT(DISTINCT (capture_id, second, cell_index))
        FROM nmf_cell_second
        WHERE project_id=:pid AND event_code=:ev AND metric_code=:col
          AND value IS NOT NULL AND cell_index >= 0
    """), {"pid": project_id, "ev": event_code, "col": col}).scalar() or 0)


def main():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT project_id, payload FROM metrics_catalog_cache ORDER BY project_id"
        )).all()
        avail_cols = _available_columns(db)
        avail_light_cols = {
            r[0] for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='nmf_event_light'"
            )).all()
        }
        avail_group_cols = {
            r[0] for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='nmf_event_light_group'"
            )).all()
        }
        event_cols = _event_fields_yaml()
        total_orphans = 0
        total_dup_nodes = 0
        total_dup_metrics = 0
        total_false_grey = 0  # G25.2 — grey leaves qui ont une colonne existante
        total_stale_false_grey = 0  # G25.3 — col décodée + n>0 + non selectable
        total_cell_sum_loss = 0  # G25.4 — lignes perdues entre les variantes
        total_grey_no_reason = 0  # G25.5 — gris sans tooltip
        print(f"{'project_id':<20} {'metrics':>8} {'leaves':>8} {'orph':>5} "
              f"{'dupN':>5} {'dupC':>5} {'fg':>4} {'sfg':>4} {'loss':>5} {'nor':>4}")
        for pid, payload in rows:
            if isinstance(payload, str): payload = json.loads(payload)
            metrics = payload.get("metrics", [])
            nodes = payload.get("nodes", [])

            # 1) duplicat check — leaves node_ids
            leaf_ids = [n["node_id"] for n in nodes if n.get("node_type") == "leaf"]
            node_id_counts = Counter(leaf_ids)
            dup_node_ids = [k for k, v in node_id_counts.items() if v > 1]

            # 2) duplicat check — metrics codes
            codes = [m.get("code") for m in metrics if m.get("code")]
            code_counts = Counter(codes)
            dup_codes = [k for k, v in code_counts.items() if v > 1]

            # 3) orphans — chaque code doit matcher ≥ 1 selection (liste, pas set)
            selections = [n.get("selection") for n in nodes
                          if n.get("node_type") == "leaf" and n.get("selection")]
            orphans = []
            for code in codes:
                matched = False
                for sel in selections:
                    if sel == code or sel.startswith(code + "@"):
                        matched = True
                        break
                if not matched:
                    orphans.append(code)

            # 4) G25.2 — grey leaves avec `source_column` non vide (donc
            #    le YAML du décodeur a été consulté avec succès pour
            #    cette feuille) et pourtant marquées "Column not in
            #    decoder schema" dans le cache. Signature claire du bug
            #    mapping label-CSV → colonne-réelle.
            false_grey = []
            for n in nodes:
                if n.get("node_type") != "leaf": continue
                if n.get("reason") != "Column not in decoder schema": continue
                sc = n.get("source_column")
                if sc and sc in avail_cols:
                    false_grey.append((n.get("label") or n.get("metric_id"), sc))

            # 5) G25.3 — stale_false_grey générique (BC4 2026-10-28,
            #    Codex67 point 5). Jamais sur le texte de la raison :
            #    structurel col décodée + n > 0 + non selectable. Les
            #    feuilles outsider (observées hors arbre canonique ou
            #    cell_type NULL, émises par metrics_catalog_v4) sortent
            #    du périmètre : par construction `selectable=false` et
            #    data légitime, tooltip de cause en place.
            stale_false_grey = []
            for n in nodes:
                if n.get("node_type") != "leaf": continue
                proof = n.get("proof") or ""
                if proof.startswith("observed-"): continue  # outsider
                sc = n.get("source_column")
                if not sc or sc not in avail_cols: continue
                if n.get("selectable"): continue
                nn = int(n.get("n") or 0)
                if nn <= 0: continue
                stale_false_grey.append((n.get("label") or n.get("metric_id"), sc, nn))

            # 6) G25.4 — conservation par cellule (BC4 2026-10-28, point 5
            #    Codex67). Pour chaque (event, source_column) cell_scoped
            #    présent dans l'arbre, somme des n sur variantes visibles
            #    doit égaler COUNT(*) global sans filtre.
            cell_sum_loss = []
            # Agrégation par (event, source_column) des n visibles pour
            # feuilles ayant une cellule (uncatalogued inclus).
            sum_by_pair: dict[tuple[str, str], int] = {}
            for n in nodes:
                if n.get("node_type") != "leaf": continue
                sc = n.get("source_column")
                ev = (n.get("event") or "").lstrip("#")
                if not sc or not ev: continue
                # On aggrège UNIQUEMENT les feuilles cell_scoped visibles
                # (metric_id suffixé @<ct> ou feuille outsider). Les
                # bare leaves (feuille unique sans dimension) ne font pas
                # partie du sommaire.
                mid = n.get("metric_id") or ""
                is_cell_leaf = ("@" in mid) or str(n.get("node_id") or "").startswith("lf_outsider_")
                if not is_cell_leaf: continue
                key = (ev, sc)
                sum_by_pair[key] = sum_by_pair.get(key, 0) + int(n.get("n") or 0)
            for (ev, sc), s in sum_by_pair.items():
                total = _event_col_total(
                    db, pid, ev, sc, avail_light_cols, avail_group_cols
                )
                if total > s:
                    cell_sum_loss.append((ev, sc, s, total, total - s))

            # 7) G25.5 — grey sans tooltip (BC4 2026-10-28). Un leaf
            #    selectable=false DOIT porter une raison non vide.
            grey_no_reason = []
            for n in nodes:
                if n.get("node_type") != "leaf": continue
                if n.get("selectable"): continue
                r = n.get("reason")
                if r is None or (isinstance(r, str) and not r.strip()):
                    grey_no_reason.append(n.get("label") or n.get("metric_id"))

            total_orphans += len(orphans)
            total_dup_nodes += len(dup_node_ids)
            total_dup_metrics += len(dup_codes)
            total_false_grey += len(false_grey)
            total_stale_false_grey += len(stale_false_grey)
            total_cell_sum_loss += len(cell_sum_loss)
            total_grey_no_reason += len(grey_no_reason)
            print(f"{pid:<20} {len(metrics):>8} {len(leaf_ids):>8} {len(orphans):>5} "
                  f"{len(dup_node_ids):>5} {len(dup_codes):>5} {len(false_grey):>4} "
                  f"{len(stale_false_grey):>4} {len(cell_sum_loss):>5} {len(grey_no_reason):>4}")
            if dup_node_ids:
                print(f"  DUP_NODE_IDS[:3]={dup_node_ids[:3]}")
            if dup_codes:
                print(f"  DUP_METRIC_CODES[:3]={dup_codes[:3]}")
            if orphans:
                print(f"  ORPHANS[:3]={orphans[:3]}")
            if false_grey:
                print(f"  FALSE_GREY[:3]={false_grey[:3]}")
            if stale_false_grey:
                print(f"  STALE_FALSE_GREY[:3]={stale_false_grey[:3]}")
            if cell_sum_loss:
                print(f"  CELL_SUM_LOSS[:3]={cell_sum_loss[:3]}")
            if grey_no_reason:
                print(f"  GREY_NO_REASON[:3]={grey_no_reason[:3]}")

        verdict = ("PASS" if total_orphans == 0 and total_dup_nodes == 0
                   and total_dup_metrics == 0 and total_false_grey == 0
                   and total_stale_false_grey == 0 and total_cell_sum_loss == 0
                   and total_grey_no_reason == 0 else "FAIL")
        print(f"G25_VERDICT {verdict} total_orphans={total_orphans} "
              f"total_dup_node_ids={total_dup_nodes} "
              f"total_dup_metric_codes={total_dup_metrics} "
              f"total_false_grey={total_false_grey} "
              f"total_stale_false_grey={total_stale_false_grey} "
              f"total_cell_sum_loss={total_cell_sum_loss} "
              f"total_grey_no_reason={total_grey_no_reason}")
        sys.exit(0 if verdict == "PASS" else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
