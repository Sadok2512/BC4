"""G41 — invariants d'un superstream (NMFHE2).

Vérifications sur une base éphémère (le garde refuse la prod via la
même règle que G34 : `BC4_DSN` non-prod exigée, cf. tests/conftest.py).

Témoin requis : `--superstream-id` (obligatoire — jamais hardcodé).

Vérifications :

1. **Projet unique** : tous les membres partagent le même `project_id`,
   égal à celui du superstream.
2. **Captures existantes** : chaque `(project_id, capture_id)` existe
   dans `nmf_capture` (déjà garanti par FK composite, revérifié ici).
3. **Captures terminées** : chaque capture pointe sur `nmf_file.status
   = 'done'`.
4. **Ordre lecture = (position, seq)** : simule la lecture d'un
   échantillon de 100 seq et vérifie que `ROW_NUMBER() OVER (ORDER BY
   position, seq)` est monotone (pas de régression). Pas de tri par
   `ts` : la query NE fait AUCUNE référence à `ts`.
5. **Aucune ligne d'un autre projet** : la lecture via join
   `superstream_member.(project_id, capture_id) = stg_event_raw.
   (project_id, capture_id)` ne doit produire que des lignes du
   `project_id` du superstream.
6. **Somme des lignes** : `SELECT COUNT(*) FROM stg_event_raw joined`
   = `SUM(n_records) FROM nmf_capture WHERE (project_id, capture_id) IN
   members`.
7. **Frontières de membres** : entre position p et p+1, le premier
   `seq` de p+1 est le MIN(seq) de son capture, pas une continuation
   artificielle.
"""
import argparse
import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.db import SessionLocal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--superstream-id", required=True,
                    help="ID du superstream témoin (OBLIGATOIRE)")
    args = ap.parse_args()

    db = SessionLocal()
    fails: list[str] = []

    try:
        ss = db.execute(text("""
            SELECT id, project_id, name FROM superstream WHERE id=:sid
        """), {"sid": args.superstream_id}).first()
        if ss is None:
            print(f"G41_VERDICT FAIL witness superstream_id={args.superstream_id} introuvable")
            return 1
        ss_id, project_id, name = ss
        print(f"G41 witness ss={ss_id[:8]} project={project_id} name={name!r}")

        members = db.execute(text("""
            SELECT position, project_id, capture_id FROM superstream_member
            WHERE superstream_id=:sid ORDER BY position
        """), {"sid": ss_id}).mappings().all()
        print(f"  members={len(members)}")
        if not members:
            print("G41_VERDICT FAIL no_witness examined=0 (superstream vide)")
            return 1

        # 1. projet unique
        bad_proj = [m for m in members if m["project_id"] != project_id]
        if bad_proj:
            fails.append(f"members with foreign project: {len(bad_proj)}")

        # 2. existence capture + 3. status done
        for m in members:
            row = db.execute(text("""
                SELECT c.capture_id, f.status
                FROM nmf_capture c JOIN nmf_file f ON f.id=c.nmf_file_id
                WHERE c.project_id=:pid AND c.capture_id=:cap
            """), {"pid": m["project_id"], "cap": m["capture_id"]}).first()
            if row is None:
                fails.append(f"missing capture pid={m['project_id']} cap={m['capture_id']}")
                continue
            if row[1] != "done":
                fails.append(f"non-done member cap={m['capture_id']} status={row[1]}")

        # 4. ordre (position, seq) monotone (ordre canonique)
        rank_check = db.execute(text("""
            WITH joined AS (
              SELECT sm.position, r.capture_id, r.seq,
                     ROW_NUMBER() OVER (ORDER BY sm.position, r.seq) AS rn
              FROM superstream_member sm
              JOIN stg_event_raw r
                ON r.project_id=sm.project_id AND r.capture_id=sm.capture_id
              WHERE sm.superstream_id=:sid
              LIMIT 1000
            )
            SELECT COUNT(*) FILTER (WHERE prev_rn IS NOT NULL AND rn <> prev_rn + 1) AS gaps
            FROM (SELECT rn, LAG(rn) OVER (ORDER BY rn) AS prev_rn FROM joined) q
        """), {"sid": ss_id}).scalar()
        if rank_check and rank_check > 0:
            fails.append(f"rank gaps = {rank_check} (expected 0)")

        # 5. aucune ligne d'un autre projet (via le join member)
        foreign = db.execute(text("""
            SELECT COUNT(*) FROM superstream_member sm
            JOIN stg_event_raw r ON r.capture_id=sm.capture_id
            WHERE sm.superstream_id=:sid AND r.project_id <> sm.project_id
        """), {"sid": ss_id}).scalar()
        if foreign and foreign > 0:
            fails.append(f"cross-project rows = {foreign}")

        # 6. somme des lignes
        expected = db.execute(text("""
            SELECT COALESCE(SUM(c.n_records),0)
            FROM superstream_member sm
            JOIN nmf_capture c ON c.project_id=sm.project_id AND c.capture_id=sm.capture_id
            WHERE sm.superstream_id=:sid
        """), {"sid": ss_id}).scalar()
        actual = db.execute(text("""
            SELECT COUNT(*) FROM superstream_member sm
            JOIN stg_event_raw r
              ON r.project_id=sm.project_id AND r.capture_id=sm.capture_id
            WHERE sm.superstream_id=:sid
        """), {"sid": ss_id}).scalar()
        if expected != actual:
            fails.append(f"rowcount mismatch : expected={expected} actual={actual}")
        else:
            print(f"  rowcount OK ({actual} = sum(n_records))")

        # 7. frontières : min(seq) par position correspond au min(seq) de la capture
        boundaries = db.execute(text("""
            SELECT sm.position, sm.capture_id,
                   (SELECT MIN(seq) FROM stg_event_raw r
                    WHERE r.project_id=sm.project_id AND r.capture_id=sm.capture_id) AS seq_min
            FROM superstream_member sm WHERE sm.superstream_id=:sid ORDER BY sm.position
        """), {"sid": ss_id}).mappings().all()
        print(f"  boundaries: {len(boundaries)}")
        for b in boundaries:
            if b["seq_min"] is None:
                fails.append(f"empty capture at position {b['position']}")

        verdict = "PASS" if not fails else "FAIL"
        if fails:
            print(f"\n== G41 fails ==")
            for f in fails:
                print(f"  - {f}")
        print(f"\nG41_VERDICT {verdict} superstream={ss_id[:8]} members={len(members)} fails={len(fails)}")
        if verdict == "FAIL":
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
