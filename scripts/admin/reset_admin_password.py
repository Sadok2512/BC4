#!/usr/bin/env python3
"""Reset `app_user.password_hash` pour un admin ciblé, sous DEPLOY_LOCK BC3.

Un seul chemin tracé pour toute rotation de hash admin, en remplacement
des `UPDATE` ou `INSERT … ON CONFLICT` manuels (incident BC3 2026-10-30
07:52Z consigné dans `CHANGELOG.md`).

- Génère un mot de passe aléatoire URL-safe de 24 caractères (≥160 bits)
  ou accepte un mot de passe fourni en entrée (`--password-stdin`).
- Hash en argon2id via `app.services.auth.hash_password`.
- `UPDATE app_user SET password_hash=:h WHERE email=:e` sous
  DEPLOY_LOCK (holder=BC3). Pas d'ON CONFLICT, pas de création.
- Trace `scripts/admin/reset_admin_password.log` (append), horodaté UTC,
  avec `email`, `--reason`, `holder`, `pid` du conteneur, et **jamais** le
  hash ni le mot de passe en clair.

Usage :
  docker exec -e BC4_DEPLOY_LOCK_PATH=/tmp/DEPLOY_LOCK bc4-api-1 \\
    python scripts/admin/reset_admin_password.py \\
      --email admin@bc4.local \\
      --reason "Codex67 bloqué post-upsert BC3 07:52Z"

Le mot de passe généré est imprimé **une seule fois** sur stdout, à
communiquer hors-canal au destinataire. Il n'est jamais logué.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, "/app")
from app.scripts.deploy_guard import require_bc3_deploy_lock, DeployLockError  # noqa: E402
from app.services.auth import hash_password  # noqa: E402


LOG_PATH = Path("/app/scripts/admin/reset_admin_password.log")


def _append_log(email: str, reason: str, holder: str, pid: int, status: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts}\temail={email}\treason={reason}\tholder={holder}\tpid={pid}\tstatus={status}\n"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="email de l'admin à réinitialiser")
    ap.add_argument("--reason", required=True, help="justification écrite (ira dans le log)")
    ap.add_argument("--password-stdin", action="store_true",
                    help="lire le mot de passe sur stdin au lieu d'en générer un")
    ap.add_argument("--length", type=int, default=24,
                    help="longueur du mot de passe généré (défaut 24)")
    args = ap.parse_args()

    email = args.email.strip().lower()
    if not email:
        print("reset_admin_password FAIL: --email required", file=sys.stderr)
        return 2

    try:
        lock_path = require_bc3_deploy_lock(action="admin_password.reset")
    except DeployLockError as exc:
        print(f"reset_admin_password FAIL: {exc}", file=sys.stderr)
        return 3

    if args.password_stdin:
        password = sys.stdin.readline().strip()
        if not password:
            print("reset_admin_password FAIL: empty stdin", file=sys.stderr)
            return 4
    else:
        password = secrets.token_urlsafe(args.length)

    h = hash_password(password)
    dsn = os.environ["BC4_DSN"]
    eng = create_engine(dsn)
    with eng.begin() as conn:
        res = conn.execute(
            text("UPDATE app_user SET password_hash=:h WHERE email=:e RETURNING id"),
            dict(h=h, e=email),
        ).fetchone()

    if not res:
        _append_log(email, args.reason, "BC3", os.getpid(), "NOT_FOUND")
        print(f"reset_admin_password FAIL: email={email} not found in app_user",
              file=sys.stderr)
        return 5

    _append_log(email, args.reason, "BC3", os.getpid(), "OK")
    print(f"reset_admin_password OK email={email} id={res[0]} lock_path={lock_path}")
    print(f"NEW_PASSWORD={password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
