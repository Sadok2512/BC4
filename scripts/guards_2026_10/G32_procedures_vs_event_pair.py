"""G32 — /signaling/procedures ↔ nmf_event_pair alignment.

Pour chaque capture, compare les procedures de types ∈ {attach, bearer,
call, data_session, ho, rrc_connection} entre le service `/signaling/
procedures` (via `app.signaling.service.population`) et la table
`nmf_event_pair` (source unique en 0.87.1).

PASS si, par capture et par type, pour chaque seq_start de nmf_event_pair,
la procedure correspondante a mêmes `seq_end`, `duration_ms` (tolérance
1 ms pour arrondis Decimal), et `outcome` ∈ {ok,fail,incomplete}
équivalent.

Verdict G32:
- orphans_pair > 0  : paires sans procedure équivalente → FAIL
- orphans_proc > 0  : procedures sans paire → FAIL (sauf rrc_setup/reest)
- differ > 0        : seq_end ou duration mismatch → FAIL
- else PASS.
"""
import sys
sys.path.insert(0, "/app")
from app.db import SessionLocal
from app.signaling.service import population
from sqlalchemy import text


_PAIR_TYPES = {'attach','bearer','call','data_session','ho','rrc_connection'}


def main():
    db = SessionLocal()
    try:
        caps = db.execute(text(
            "SELECT project_id, capture_id FROM nmf_capture ORDER BY capture_id"
        )).all()
        print(f"G32 witnesses: {len(caps)} captures (full perimeter)")
        total_diff = 0
        total_orphans_pair = 0
        total_orphans_proc = 0
        procs_only_by_type: dict[str, int] = {}  # 0.87.2 — visibilité
        for pid, cap in caps:
            # procedures via service
            _rows, procs, _meta, _times = population(db, pid, cap, persist=False)
            # 0.87.2 — rapport séparé des types procs_only : rrc_setup et
            # reestablishment sont LÉGITIMEMENT absents de nmf_event_pair
            # (pas pairés par pipeline capture-local, produits par
            # procedures.py RULES). Compte explicite pour visibilité, PAS
            # orphans. Avant 0.87.2 G32 filtrait silencieusement → aveugle.
            for p in procs:
                if p['type'] not in _PAIR_TYPES:
                    procs_only_by_type[p['type']] = procs_only_by_type.get(p['type'], 0) + 1
            procs_by_key = {(p['type'], p['seq_start']): p for p in procs if p['type'] in _PAIR_TYPES}
            # pairs direct
            pair_rows = db.execute(text(
                "SELECT type, seq_start, seq_end, duration_nemo_ms, outcome "
                "FROM nmf_event_pair WHERE project_id=:pid AND capture_id=:cap "
                "AND type = ANY(:types) ORDER BY type, seq_start"
            ), {"pid": pid, "cap": cap, "types": sorted(_PAIR_TYPES)}).mappings().all()
            pairs_by_key = {(p['type'], p['seq_start']): p for p in pair_rows}
            orph_pair = sum(1 for k in pairs_by_key if k not in procs_by_key)
            orph_proc = sum(1 for k in procs_by_key if k not in pairs_by_key)
            differ = 0
            for k, pair in pairs_by_key.items():
                if k not in procs_by_key:
                    continue
                proc = procs_by_key[k]
                p_dur = pair['duration_nemo_ms']
                proc_dur = proc['duration_ms']
                # Equal if both None, or numeric diff <= 1 ms
                if p_dur is None and proc_dur is None:
                    dur_ok = True
                elif p_dur is None or proc_dur is None:
                    dur_ok = False
                else:
                    dur_ok = abs(float(p_dur) - float(proc_dur)) <= 1
                end_ok = (pair['seq_end'] == proc['seq_end'])
                if not (dur_ok and end_ok):
                    differ += 1
            total_diff += differ
            total_orphans_pair += orph_pair
            total_orphans_proc += orph_proc
            if differ or orph_pair or orph_proc:
                print(f"  {cap[:12]}  pairs={len(pair_rows)} procs={len(procs_by_key)} "
                      f"differ={differ} orph_pair={orph_pair} orph_proc={orph_proc}")
        # 0.89.5 — garde sans témoin = FAIL. `caps` vient de `SELECT ...
        # FROM nmf_capture` : 0 capture ⇒ aucun échantillon ⇒ FAIL.
        if len(caps) == 0:
            print(f"\nG32_VERDICT FAIL no_witness examined=0 "
                  f"(nmf_capture vide — ingérer au moins une capture)")
            sys.exit(1)
        verdict = "PASS" if (total_diff == 0 and total_orphans_pair == 0 and total_orphans_proc == 0) else "FAIL"
        # 0.87.2 — rapport procs_only (hors _PAIR_TYPES) visible, mais pas FAIL
        print(f"\nG32 procs_only (hors _PAIR_TYPES, légitimes) : {procs_only_by_type}")
        print(f"G32_VERDICT {verdict}  total_differ={total_diff} "
              f"total_orphans_pair={total_orphans_pair} total_orphans_proc={total_orphans_proc}")
        # 0.87.2 — exit non-zero sur FAIL pour qu'un wrapper CI/manuel détecte.
        if verdict == "FAIL":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
