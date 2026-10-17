"""Audit G0–G11 (projet REF). Lecture seule. Fast via chargement mémoire."""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "/app")
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

PID = "7e656b8c6c19"


def q(db, sql, **p):
    return db.execute(text(sql), p).all()


def pair_median_p90(cm_rows, mr_rows, window=100):
    """cm_rows: list[(capture_id, seq, cm_val)]; mr_rows: list[(capture_id, seq, rrc_val)].
    Pour chaque cm, trouver le mr le plus proche en seq dans la même capture
    dans la fenêtre ±window. Retourne (n_pairs, median|Δ|, p90|Δ|)."""
    mr_by_cap: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for cap, seq, v in mr_rows:
        mr_by_cap[cap].append((int(seq), float(v)))
    for v in mr_by_cap.values():
        v.sort()
    deltas: list[float] = []
    for cap, seq, cm in cm_rows:
        arr = mr_by_cap.get(cap, [])
        if not arr:
            continue
        # linear search ok (arr~hundreds, we have thousands of cm)
        s = int(seq)
        best = None
        best_dist = window + 1
        for mseq, mv in arr:
            d = abs(mseq - s)
            if d <= window and d < best_dist:
                best_dist = d
                best = mv
            if mseq - s > window:
                break
        if best is None:
            continue
        deltas.append(abs(float(cm) - best))
    deltas.sort()
    n = len(deltas)
    med = deltas[n // 2] if n else None
    p90 = deltas[int(n * 0.9)] if n else None
    return n, med, p90


def main() -> int:
    with SessionLocal() as db:
        print("═══════ G0 — RSRP mapping proof per field ═══════")
        print()
        print("Requête n_valid (zone RSRP [-140,-44]) :")
        rows = q(db, """
            SELECT 'cell0_rsrq_db' AS field, COUNT(*) FILTER (WHERE v BETWEEN -140 AND -44) n
            FROM (SELECT (raw_fields->>'cell0_rsrq_db')::float v FROM stg_event_raw
                  WHERE project_id=:pid AND event_code='CELLMEAS') q
            UNION ALL
            SELECT 'cell0_c7', COUNT(*) FILTER (WHERE v BETWEEN -140 AND -44)
            FROM (SELECT (raw_fields->>'cell0_c7')::float v FROM stg_event_raw
                  WHERE project_id=:pid AND event_code='CELLMEAS') q
            UNION ALL
            SELECT 'cell0_c8', COUNT(*) FILTER (WHERE v BETWEEN -140 AND -44)
            FROM (SELECT (raw_fields->>'cell0_c8')::float v FROM stg_event_raw
                  WHERE project_id=:pid AND event_code='CELLMEAS') q
        """, pid=PID)
        for f, n in rows:
            print(f"  {f:16}  n_valid={n}")
        print()

        # Charger mr une fois
        mr_rows = db.execute(text("""
            SELECT se.capture_id, se.seq, po.value_converted::float
            FROM param_occurrence po JOIN stg_event se ON se.id = po.stg_event_id
            WHERE po.project_id = :pid
              AND po.path LIKE '%measResultPCell/rsrpResult'
              AND po.value_converted IS NOT NULL
        """), {"pid": PID}).all()
        mr_rows = [(r[0], r[1], r[2]) for r in mr_rows if -140 <= r[2] <= -44]

        print("Per-event Δ (|cm - rrc_pcell|) fenêtre (capture_id, seq ±100), ordre canonique :")
        print(f"  (sample RRC rsrpResult PCell n = {len(mr_rows)})")
        for f in ("cell0_rsrq_db", "cell0_c7"):
            cm_rows = db.execute(text(f"""
                SELECT capture_id, seq, (raw_fields->>'{f}')::float
                FROM stg_event_raw
                WHERE project_id = :pid AND event_code = 'CELLMEAS'
                  AND raw_fields->>'{f}' IS NOT NULL
            """), {"pid": PID}).all()
            cm_rows = [(r[0], r[1], float(r[2])) for r in cm_rows if -140 <= r[2] <= -44]
            n, med, p90 = pair_median_p90(cm_rows, mr_rows)
            verdict = "proven" if med is not None and med <= 2.0 else "rejected"
            print(f"  {f:16}  n_pairs={n:5d}  median|Δ|={None if med is None else round(med,2)} dB  p90|Δ|={None if p90 is None else round(p90,2)} dB  verdict={verdict}")
        print()
        print("Profil retenu par profile_cellmeas :")
        from app.measure.profiling import profile_cellmeas
        m = profile_cellmeas(db, PID)
        print(f"  rssi <- {m.rssi}")
        print(f"  rsrp <- {m.rsrp}")
        print(f"  rsrq <- {m.rsrq}")
        print(f"  sinr <- {m.sinr}")
        print()
        print("Requête mp.rsrp (populate.py:460 UPDATE SET rsrp=:rsrp, filtré par RSRP_RANGE côté Python) :")
        n_rsrp = db.execute(text(
            "SELECT COUNT(rsrp) FROM measurement_points WHERE project_id=:pid"
        ), {"pid": PID}).scalar()
        print(f"  SELECT COUNT(rsrp) FROM measurement_points → {n_rsrp}")
        print()
        print('cell0_c8 avg=−3,1 : zone RSRQ/SINR, n_valid=0 en zone RSRP → "ambigu, non affecté" sera déclaré dans le profil persisté (section D).')
        print()

        print("═══════ G1 — tech vient de system=9 (EN-DC) ═══════")
        # mp n'a pas de colonne `system` ; on remonte via stg_event_raw.system
        # joint par (project_id, capture_id, seq).
        print("Requête : jointure mp(tech='NR') ↔ stg_event_raw.system par (project,capture,seq)")
        for ec, sy, n in q(db, """
            SELECT mp.event_code, s.system, COUNT(*)
            FROM measurement_points mp
            JOIN stg_event_raw s
              ON s.project_id = mp.project_id
             AND s.capture_id = mp.capture_id
             AND s.seq = mp.seq
            WHERE mp.project_id=:pid AND mp.tech='NR'
            GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10
        """, pid=PID):
            print(f"  event_code={ec}  system={sy}  count={n}")
        print()
        print("Vérif stg_event_raw.system présent/absent :")
        for sy, n in q(db, """
            SELECT system, COUNT(*) FROM stg_event_raw WHERE project_id=:pid
            GROUP BY system ORDER BY 2 DESC LIMIT 5
        """, pid=PID):
            print(f"  stg_event_raw.system={sy!r}  count={n}")
        print()

        print("═══════ G2 — preuve RSRP per-event ═══════")
        from app.measure.proof import prove_rsrp_per_event
        if m.rsrp is None:
            print("NON FAIT : profile_cellmeas renvoie rsrp=None (aucun champ ne satisfait les règles).")
        else:
            p = prove_rsrp_per_event(db, PID, m.rsrp, seq_window=100).as_dict()
            n_pairs = p["n_pairs"]
            med = p["median_abs_delta"]
            # p90 — reconstruit depuis une relance stricte en Python en mémoire
            cm_rows = db.execute(text(f"""
                SELECT capture_id, seq, (raw_fields->>'{m.rsrp}')::float
                FROM stg_event_raw WHERE project_id=:pid AND event_code='CELLMEAS'
                  AND raw_fields->>'{m.rsrp}' IS NOT NULL
            """), {"pid": PID}).all()
            cm_rows = [(r[0], r[1], float(r[2])) for r in cm_rows if -140 <= r[2] <= -44]
            _, _, p90 = pair_median_p90(cm_rows, mr_rows)
            print(f"  field={m.rsrp}  n_pairs={n_pairs}  median|Δ|={None if med is None else round(med,2)} dB  p90|Δ|={None if p90 is None else round(p90,2)} dB  verdict={p['verdict']}")
            print(f"  reason={p['reason']}")
        print("Remplacement de run_proof legacy par prove_rsrp_per_event dans _oneshot_populate_mp_ref.py : à shipper en section D.")
        print()

        print("═══════ G3 — débit : DSUMMARY vs PDCPRATED/RLCRATE/MACRATE ═══════")
        print("Requête : 10 DSUMMARY avec dt (bytes/intervalle), PDCPRATE DL median sur même fenêtre :")
        rows = q(db, """
            WITH ds AS (
                SELECT capture_id, seq, (raw_fields->>'bytes_transferred')::bigint AS b, ts
                FROM stg_event_raw
                WHERE project_id=:pid AND event_code='DSUMMARY'
                  AND raw_fields->>'bytes_transferred' IS NOT NULL
                ORDER BY capture_id, seq
            )
            SELECT * FROM ds LIMIT 10
        """, pid=PID)
        print(f"  (10 premiers DSUMMARY sur {len(q(db, 'SELECT 1 FROM stg_event_raw WHERE project_id=:pid AND event_code=:ec', pid=PID, ec='DSUMMARY'))} total)")
        for cap, seq, b, ts in rows:
            # Chercher un PDCPRATED dans ±100 seq de la même capture
            pdcp = q(db, """
                SELECT (raw_fields->>'c4')::float, (raw_fields->>'c5')::float, (raw_fields->>'c6')::float
                FROM stg_event_raw
                WHERE project_id=:pid AND event_code='PDCPRATED'
                  AND capture_id=:cap AND abs(seq - :s) <= 100
                LIMIT 3
            """, pid=PID, cap=cap, s=seq)
            pdcp_vals = []
            for c4, c5, c6 in pdcp:
                for v in (c4, c5, c6):
                    if v is not None and 0 <= v <= 300_000:
                        pdcp_vals.append(v)
            # Débit APP calculé : bytes / dt. dt inconnu ici — on sort juste bytes + médiane PDCP fenêtre
            print(f"  cap={cap[:8]} seq={seq} ts={ts} bytes={b} PDCPRATED_median_window={statistics.median(pdcp_vals) if pdcp_vals else 'N/D'}")
        print()
        print('Analyse : DSUMMARY est **cumulatif** (bytes_transferred croît) OU **par intervalle** — à déterminer par delta_byt entre 2 DSUMMARY successifs par capture :')
        pairs = q(db, """
            WITH ds AS (
                SELECT capture_id, seq,
                       (raw_fields->>'bytes_transferred')::bigint b,
                       LAG((raw_fields->>'bytes_transferred')::bigint)
                           OVER (PARTITION BY capture_id ORDER BY seq) AS b_prev
                FROM stg_event_raw
                WHERE project_id=:pid AND event_code='DSUMMARY'
            )
            SELECT COUNT(*) FILTER (WHERE b > b_prev) AS strictly_increasing,
                   COUNT(*) FILTER (WHERE b < b_prev) AS decreasing,
                   COUNT(*) FILTER (WHERE b = b_prev) AS equal,
                   COUNT(*) FILTER (WHERE b_prev IS NULL) AS first_in_capture
            FROM ds
        """, pid=PID)
        for inc, dec, eq, first in pairs:
            print(f"  strictly_increasing={inc}  decreasing={dec}  equal={eq}  first_in_capture={first}")
            if dec >= inc:
                print("  → DSUMMARY semble **par intervalle** (bytes propres à chaque DSUMMARY).")
            else:
                print("  → DSUMMARY est **cumulatif** (bytes croissent monotone). dt = ts_i − ts_{i-1} ; bytes = b_i − b_{i-1}.")
        print()
        print('Témoin : chercher un DSUMMARY ~39 Mo en ~10 s (incar) :')
        for cap, seq, b, ts in q(db, """
            SELECT capture_id, seq, (raw_fields->>'bytes_transferred')::bigint, ts
            FROM stg_event_raw
            WHERE project_id=:pid AND event_code='DSUMMARY'
              AND (raw_fields->>'bytes_transferred')::bigint BETWEEN 35000000 AND 45000000
            ORDER BY seq LIMIT 5
        """, pid=PID):
            print(f"  cap={cap[:8]} seq={seq} ts={ts} bytes={b}")
        print()

        print("═══════ G4 — pondération transferts ═══════")
        print("Table transferts (compute_transfers in-memory) :")
        from app.measure.throughput import compute_transfers
        ts = compute_transfers(db, PID)
        proven = [t for t in ts if t.verdict == "proven"]
        mbps = sorted(float(t.thrpt_mbps) for t in proven if t.thrpt_mbps is not None)
        n = len(mbps)
        if n:
            p10 = mbps[int(n*0.1)]; p50 = mbps[n//2]; p90 = mbps[int(n*0.9)]
            print(f"  n_transferts_proven={n}  P10={p10:.2f}  P50={p50:.2f}  P90={p90:.2f}  Mbit/s")
        else:
            print("  NON FAIT : 0 transferts proven")
        print(f"  (vs mp.dl : {db.execute(text('SELECT COUNT(dl) FROM measurement_points WHERE project_id=:pid'), {'pid': PID}).scalar()} points, mais chaque transfert = N lignes mp → PAS la base statistique.)")
        print()

        print("═══════ G5 — profil CELLMEAS persisté ═══════")
        tbl = db.execute(text("SELECT to_regclass('cellmeas_profile')"), {}).scalar()
        if tbl is None:
            print("NON FAIT : table cellmeas_profile n'existe pas. À créer en section D.")
        else:
            print(f"table existe : {tbl}")
            for r in q(db, "SELECT * FROM cellmeas_profile WHERE project_id=:pid LIMIT 5", pid=PID):
                print(f"  {r}")
        print()

        print("═══════ G6 — catalogue v2 réconcilié ═══════")
        try:
            from app.kpi.catalog_v2 import ALIASES_REPORT, CANONICAL_COUNT, ALIASES_COUNT, TOTAL_INPUT_ROWS
            print(f"  TOTAL_INPUT_ROWS = {TOTAL_INPUT_ROWS}  CANONICAL_COUNT = {CANONICAL_COUNT}  ALIASES_COUNT = {ALIASES_COUNT}")
            print(f"  14 codes alias → canonique :")
            for a in ALIASES_REPORT[:14]:
                print(f"    {a['alias']:38}  ↔  {a['canonical']:30}  — {a['reason']}")
        except Exception as e:
            print(f"NON FAIT : {e!r}")
        print()
        print("response_model Pydantic sur /projects/{id}/kpi/* : NON FAIT dans ce rapport (dev section D).")
        print()

        print("═══════ G7 — nmf_count & sérialisation ingest ═══════")
        nmf = db.execute(text("SELECT COUNT(*) FROM nmf_file WHERE project_id=:pid"), {"pid": PID}).scalar()
        print(f"  nmf_count = {nmf} / 18 attendu")
        print("  Sérialisation populate_param_occurrence / populate_measurement_points : NON FAIT (dev section D).")
        print()

        print("═══════ G8 — ECGI ventilation par attribution ═══════")
        print("Requête ventilation (mp.ecgi par mode) :")
        # Pour l'instant il n'y a pas de mp.ecgi_source. On compte juste mp.ecgi NULL vs non-NULL.
        rows = q(db, """
            SELECT COUNT(*) AS mp_total,
                   COUNT(ecgi) AS mp_with_ecgi,
                   COUNT(*) FILTER (WHERE ecgi IS NULL) AS mp_without_ecgi
            FROM measurement_points WHERE project_id=:pid
        """, pid=PID)
        for mp_total, mp_with, mp_without in rows:
            pct = 100.0 * mp_with / mp_total if mp_total else 0
            print(f"  mp_total={mp_total}  mp_with_ecgi={mp_with}  mp_without={mp_without}  pct={pct:.1f}%")
        # mp.ecgi_source column?
        has_src = db.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='measurement_points' AND column_name='ecgi_source'
        """)).scalar()
        print(f"  mp.ecgi_source column present : {bool(has_src)}")
        print("  Ajout mp.ecgi_source + marquage inféré : NON FAIT (dev section D).")
        print()

        print("═══════ G9 — walker BIT STRING → entier (TAC = 39233) ═══════")
        print("Requête : param_occurrence.value LIKE '%bits(%' OR LIKE '0b%'")
        rows = q(db, """
            SELECT path, value, value_converted
            FROM param_occurrence
            WHERE project_id=:pid AND (value LIKE '%bits(%' OR value LIKE '0b%' OR value LIKE '%BIT STRING%')
            LIMIT 20
        """, pid=PID)
        print(f"  n_rows_with_bits_literal = {len(rows)}")
        for p, v, vc in rows[:5]:
            print(f"    path={p[:60]} value={v!r} converted={vc!r}")
        print("Requête TAC = 39233 :")
        for p, v in q(db, """
            SELECT path, value FROM param_occurrence
            WHERE project_id=:pid AND path LIKE '%trackingAreaCode%'
            LIMIT 5
        """, pid=PID):
            print(f"    path={p[:70]} value={v!r}")
        print()

        print("═══════ G10 — listes SEQUENCE OF ═══════")
        for leaf in ("plmn-IdentityList", "interFreqCarrierFreqList", "cellReselectionPriority",
                     "neighCellConfig"):
            n = db.execute(text(
                "SELECT COUNT(*) FROM param_occurrence WHERE project_id=:pid AND path LIKE :p"
            ), {"pid": PID, "p": f"%{leaf}%"}).scalar()
            print(f"  path LIKE %{leaf}%  n={n}")
        print()

        print("═══════ G11 — group_by LTE_RF_RSRP operator_band avec N/D ═══════")
        # On relance via l'endpoint public
        import urllib.request, json as _json
        login = urllib.request.urlopen(urllib.request.Request(
            "http://api:8000/auth/login", method="POST",
            data=_json.dumps({"email": "admin@bc4.local", "password": "ChangeMeAdmin123!"}).encode(),
            headers={"Content-Type": "application/json"})).read()
        tok = _json.loads(login)["token"]
        try:
            res = urllib.request.urlopen(urllib.request.Request(
                f"http://api:8000/projects/{PID}/kpi/LTE_RF_RSRP?group_by=operator_band",
                headers={"Authorization": f"Bearer {tok}"})).read()
            d = _json.loads(res)
            groups = d.get("groups") or d.get("table") or []
            total_sum = sum(g.get("n", 0) for g in groups)
            nd = [g for g in groups if g.get("operator") in (None, "N/D") or g.get("band") in (None, "N/D")]
            print(f"  n_groups={len(groups)}  sum(n)={total_sum}")
            print(f"  N/D rows (operator or band = NULL/N/D) : {len(nd)}")
            for g in nd[:5]:
                print(f"    operator={g.get('operator')} band={g.get('band')} n={g.get('n')}")
            n_rsrp = db.execute(text("SELECT COUNT(rsrp) FROM measurement_points WHERE project_id=:pid"), {"pid": PID}).scalar()
            print(f"  mp.rsrp total (SELECT COUNT(rsrp)) : {n_rsrp}")
            # 4205 RSRP sans bande attendu :
            no_band_n = db.execute(text("""
                SELECT COUNT(*) FROM measurement_points
                WHERE project_id=:pid AND rsrp IS NOT NULL AND band IS NULL
            """), {"pid": PID}).scalar()
            print(f"  mp.rsrp sans bande (NULL) : {no_band_n}")
        except Exception as e:
            print(f"NON FAIT : {e!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
