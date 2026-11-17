#!/usr/bin/env python3
"""Rotate BC4 runtime credentials without writing their values to output.

The PostgreSQL password change, optional LLM API-key re-encryption and env
file replacement are treated as one recoverable operation.  This script must
run under the deployment lock and deliberately emits names/statuses only.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import tempfile

from cryptography.fernet import Fernet, InvalidToken
import psycopg


REQUIRED_HOLDERS = {"BC1", "BC4"}


def read_env(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text()
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value
    return raw, values


def replace_env(raw: str, replacements: dict[str, str]) -> str:
    pending = dict(replacements)
    output: list[str] = []
    for line in raw.splitlines(keepends=True):
        if "=" in line and not line.lstrip().startswith("#"):
            name = line.split("=", 1)[0].strip()
            if name in pending:
                ending = "\n" if line.endswith("\n") else ""
                output.append(f"{name}={pending.pop(name)}{ending}")
                continue
        output.append(line)
    if output and not output[-1].endswith("\n"):
        output[-1] += "\n"
    for name, value in pending.items():
        output.append(f"{name}={value}\n")
    return "".join(output)


def atomic_write_600(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=".env.rotate-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def require_lock(path: Path) -> str:
    fields: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            fields[name.strip()] = value.strip()
    holder = fields.get("holder", "")
    if holder not in REQUIRED_HOLDERS:
        raise RuntimeError("deployment lock absent or holder not authorized")
    return holder


def current_llm_key(env: dict[str, str], compose_path: Path) -> bytes:
    configured = env.get("BC4_LLM_SECRET_KEY")
    if configured:
        return configured.encode()
    compose = compose_path.read_text()
    match = re.search(r"BC4_LLM_SECRET_KEY:\s*\$\{BC4_LLM_SECRET_KEY:-([^}]+)\}", compose)
    if not match:
        raise RuntimeError("current LLM encryption key cannot be resolved")
    return match.group(1).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()

    holder = require_lock(args.lock_file)
    old_raw, env = read_env(args.env_file)
    old_pg = env.get("BC4_PGPW")
    if not old_pg or env.get("POSTGRES_PASSWORD") != old_pg:
        raise RuntimeError("PostgreSQL credential aliases are absent or inconsistent")
    old_llm = current_llm_key(env, args.compose_file)

    new_pg = secrets.token_urlsafe(48)
    new_jwt = secrets.token_urlsafe(64)
    new_llm = Fernet.generate_key()
    new_raw = replace_env(
        old_raw,
        {
            "BC4_PGPW": new_pg,
            "POSTGRES_PASSWORD": new_pg,
            "BC4_JWT_SECRET": new_jwt,
            "BC4_LLM_SECRET_KEY": new_llm.decode(),
        },
    )

    conn = psycopg.connect(
        host="127.0.0.1", port=5432, dbname="bc4", user="bc4", password=old_pg
    )
    env_written = False
    cipher_state = "absent"
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT api_key_cipher FROM settings_llm WHERE id = 1 FOR UPDATE")
            row = cursor.fetchone()
            cipher = row[0] if row else None
            new_cipher = None
            if cipher:
                try:
                    plaintext = Fernet(old_llm).decrypt(cipher.encode())
                except InvalidToken as exc:
                    raise RuntimeError("stored LLM API key cannot be decrypted") from exc
                new_cipher = Fernet(new_llm).encrypt(plaintext).decode()
                cipher_state = "reencrypted"
            cursor.execute("ALTER ROLE bc4 PASSWORD %s", (new_pg,))
            if row and cipher:
                cursor.execute(
                    "UPDATE settings_llm SET api_key_cipher = %s WHERE id = 1",
                    (new_cipher,),
                )
            atomic_write_600(args.env_file, new_raw)
            env_written = True
        conn.commit()
    except BaseException:
        conn.rollback()
        if env_written:
            atomic_write_600(args.env_file, old_raw)
        raise
    finally:
        conn.close()

    print(f"ROTATION=PASS holder={holder}")
    print("ROTATED_NAMES=BC4_PGPW,POSTGRES_PASSWORD,BC4_JWT_SECRET,BC4_LLM_SECRET_KEY")
    print(f"LLM_API_KEY_CIPHER={cipher_state}")
    print("ENV_MODE=600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
