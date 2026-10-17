"""Backfill `stg_event_raw.system` depuis la source NMF conservée.

Pour chaque `nmf_file` d'un projet, relit `/var/lib/bc4/nmf-source/{project_id}/{nmf_id}.nmf`
avec `bc4-decoder 2.1.0` (règle `_extract_system` : f[2..4]), et UPDATE la
colonne `system` par `(nmf_file_id, capture_id, seq)`.

Garde :
    SELECT system, COUNT(*) FROM stg_event_raw WHERE project_id=:pid GROUP BY 1

Appel :
    docker exec bc4-api-1 python /app/scripts/backfill_system.py 7e656b8c6c19
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/nmf_decoder")

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

NMF_ROOT = Path("/var/lib/bc4/nmf-source")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: backfill_system.py <project_id>", file=sys.stderr)
        return 2
    pid = sys.argv[1]

    # ⚠ Import DANS main() → force un fresh import si on patche /opt/nmf_decoder.
    import importlib
    import bc4_decoder as _dec
    _dec = importlib.reload(_dec)
    _extract_system = _dec._extract_system
    _fields = _dec._fields
    import re

    with SessionLocal() as db:
        files = db.execute(
            text("SELECT id, filename FROM nmf_file WHERE project_id=:pid ORDER BY uploaded_at"),
            {"pid": pid},
        ).all()
        print(f"nmf_count={len(files)}")

        before = db.execute(text("""
            SELECT COALESCE(system, '<NULL>') AS s, COUNT(*)
            FROM stg_event_raw WHERE project_id=:pid GROUP BY 1 ORDER BY 2 DESC
        """), {"pid": pid}).all()
        print("BEFORE :")
        for s, n in before:
            print(f"  system={s!r:12}  count={n}")

        total_updated = 0
        for nmf_id, filename in files:
            path = NMF_ROOT / pid / f"{nmf_id}.nmf"
            if not path.exists():
                print(f"MISS   nmf_id={nmf_id} {filename}")
                continue
            raw = path.read_bytes()
            textual = raw.decode("latin-1")
            # On rejoue le même parcours que `_iter_events` (seq compteur global
            # depuis seq=0, incrémenté UNIQUEMENT pour les lignes émises après
            # filtrage _fields+code). Si on diverge, on backfillera uniquement
            # ce qui matche. Pour être strict : (seq, event_code) joint sur l'UNIQUE
            # côté stg_event_raw : (project_id, nmf_file_id, capture_id, seq).
            # L'ingest insère capture_id = cid = sha256(raw)[:12] et seq global
            # croissant → on reconstruit ici la même séquence.
            import hashlib
            cid = hashlib.sha256(raw).hexdigest()[:12]
            seq = 0
            updates = []
            for line in textual.splitlines():
                if not line or line.startswith("#"):
                    continue
                try:
                    f = _fields(line)
                except Exception:
                    continue
                if not f:
                    continue
                seq += 1
                system = _extract_system(f)
                if system:
                    updates.append({"nid": nmf_id, "cid": cid, "s": seq, "sys": system})
            # Flush en lots.
            for i in range(0, len(updates), 5000):
                batch = updates[i:i+5000]
                db.execute(
                    text("""
                        UPDATE stg_event_raw SET system = :sys
                        WHERE project_id = :pid AND nmf_file_id = :nid
                          AND capture_id = :cid AND seq = :s
                          AND (system IS NULL OR system <> :sys)
                    """).bindparams(),
                    [dict(u, pid=pid) for u in batch],
                )
                db.commit()
            print(f"OK     nmf_id={nmf_id} seq_total={seq} with_system={len(updates)} filename={filename[:60]}")
            total_updated += len(updates)

        after = db.execute(text("""
            SELECT COALESCE(system, '<NULL>') AS s, COUNT(*)
            FROM stg_event_raw WHERE project_id=:pid GROUP BY 1 ORDER BY 2 DESC
        """), {"pid": pid}).all()
        print("AFTER  :")
        for s, n in after:
            print(f"  system={s!r:12}  count={n}")
        print(f"TOTAL_UPDATES_EMITTED={total_updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
