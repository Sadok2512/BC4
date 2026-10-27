import os
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx
import pytest


# -----------------------------------------------------------------------------
# GARDE DÉMARRAGE : interdit l'exécution de la suite contre la DB de production.
#
# Incident 2026-10-27 : fixture `clean_db` dans `tests/test_g6_cell_ref.py:58-62`
# exécute `_reset_cell_ref` → `TRUNCATE TABLE cell_ref; TRUNCATE TABLE
# reference_import` via `app.db.SessionLocal`. `SessionLocal` lit `BC4_DSN` sans
# override côté tests. Deux pytest full-suite BC3 (12:25 et 13:41-13:54) ont
# vidé la table de production, confirmée par relfilenode birth-time
# `base/5269703/6216567 = 2026-10-27 13:54:58`.
#
# Miroir de la discipline G34 (`scripts/guards_2026_10/G34_project_access.py:51-62`) :
# le test refuse de démarrer si la DSN pointe vers `bc4@{db,127.0.0.1,localhost}:5432/bc4`.
# Aucun escape hatch : la base de prod est hors-limite pour pytest.
# -----------------------------------------------------------------------------

_PROD_HOSTS = {"db", "127.0.0.1", "localhost"}
_PROD_DB_NAME = "bc4"
_PROD_DEFAULT_PORT = 5432


def _looks_like_production_dsn(dsn: str) -> tuple[bool, str]:
    """Return (is_prod, human_readable) for the given SQLAlchemy DSN."""
    if not dsn:
        return (False, "<empty>")
    normalized = dsn.replace("postgresql+psycopg", "postgresql", 1)
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    port = parsed.port or _PROD_DEFAULT_PORT
    db = (parsed.path or "").lstrip("/")
    human = f"host={host} port={port} db={db}"
    is_prod = host in _PROD_HOSTS and port == _PROD_DEFAULT_PORT and db == _PROD_DB_NAME
    return (is_prod, human)


def pytest_configure(config: pytest.Config) -> None:  # type: ignore[name-defined]
    """Refuse pytest contre la DB de production. Appelé AVANT toute collection."""
    dsn = os.environ.get("BC4_DSN", "")
    is_prod, human = _looks_like_production_dsn(dsn)
    if is_prod:
        pytest.exit(
            "\n".join(
                [
                    "[conftest] REFUS DE DÉMARRER — DSN pointe vers la base de production.",
                    f"  BC4_DSN cible: {human}",
                    "  Motif: fixtures destructrices (ex. test_g6_cell_ref.py::clean_db) exécuteraient",
                    "         `TRUNCATE TABLE cell_ref; TRUNCATE TABLE reference_import` sur la base ciblée.",
                    "  Correctif: lancer pytest contre une DB éphémère Alembic-migrée, par exemple",
                    "         BC4_DSN='postgresql+psycopg://user:pwd@ephemeral-host:PORT/dbname_test' pytest tests/",
                ]
            ),
            returncode=2,
        )


def _base() -> str:
    base = os.environ.get("BC4_API_BASE")
    if not base:
        raise RuntimeError(
            "BC4_API_BASE environment variable is required for integration tests. "
            "A silent guard guards nothing — see rules."
        )
    return base.rstrip("/")


@pytest.fixture(scope="session")
def api_base() -> str:
    return _base()


@pytest.fixture(scope="session")
def client_noauth(api_base: str):
    """Client httpx sans auth. Utilisé par G8 pour tester que les routes
    protégées renvoient bien 401 sans Bearer."""
    with httpx.Client(base_url=api_base, timeout=20.0) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client_noauth) -> str:
    email = os.environ.get("BC4_ADMIN_EMAIL")
    pw = os.environ.get("BC4_ADMIN_PASSWORD")
    if not email or not pw:
        pytest.fail("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
    r = client_noauth.post("/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        raise RuntimeError(f"Login admin échoué : {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="session")
def client(api_base: str, admin_token: str):
    """Client HTTP par défaut : signé en admin via `Authorization: Bearer`.
    B2 : l'identité ne vient plus que du JWT, pas des headers X-Actor-*."""
    with httpx.Client(
        base_url=api_base,
        timeout=20.0,
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(admin_token) -> dict[str, str]:
    """Compat pour les tests qui passent explicitement des headers."""
    return {"Authorization": f"Bearer {admin_token}"}


PARIS = "idf-t3-2026"
RENNES = "rennes-lte-2026"


# --------------------------------------------------------------------------- #
# Nettoyage AUTOMATIQUE post-session : tout projet dont le nom (ou l'id) match
# un préfixe de test est purgé. Évite de polluer l'UI avec les restes des
# gardes (G9/G10/G11 et le smoke front). La cascade FK fait le reste.
# Préfixes réservés aux tests — PAS de collision avec des noms utilisateur
# attendus (G1-G8 n'en créaient pas, G9+ oui).
_TEST_NAME_PATTERNS = (
    "smoke-",
    "smoke-nmf-",
    "smoke-row-",
    "g9-",
    "g10-",
    "g11-",
    "G11 Enrich",
)


# ---------------------------------------------------------------------------
# Sandbox LLM — snapshot/restore de `settings_llm` autour des gardes qui
# mutent la config LLM (G18, G19, G21+). Un cleanup destructif
# (`api_key:""` + `enabled:false`) détruisait la config LLM utilisateur
# dès qu'un dev lançait une garde contre l'API live. **Un test ne doit
# JAMAIS laisser un état partagé pire qu'il ne l'a trouvé.**
#
# La sauvegarde se fait au niveau du cipher Fernet (SELECT direct) pour
# préserver EXACTEMENT la clé chiffrée — l'API, par design, ne renvoie
# jamais la clé en clair, on ne peut donc pas la ré-émettre via PUT.
# ---------------------------------------------------------------------------
@contextmanager
def _snapshot_llm_state():
    """Snapshot settings_llm (id=1) au niveau DB puis restore à la sortie."""
    from sqlalchemy import text as sql_text

    from app.db import SessionLocal

    snap: dict | None = None
    with SessionLocal() as db:
        row = db.execute(
            sql_text(
                "SELECT provider, base_url, model, api_key_cipher, enabled, "
                "temperature, max_tokens FROM settings_llm WHERE id = 1"
            )
        ).one_or_none()
        if row is not None:
            snap = {
                "provider": row[0],
                "base_url": row[1],
                "model": row[2],
                "api_key_cipher": row[3],
                "enabled": row[4],
                "temperature": row[5],
                "max_tokens": row[6],
            }
    try:
        yield
    finally:
        if snap is None:
            return
        with SessionLocal() as db:
            db.execute(
                sql_text(
                    "UPDATE settings_llm SET "
                    "provider = :provider, base_url = :base_url, model = :model, "
                    "api_key_cipher = :api_key_cipher, enabled = :enabled, "
                    "temperature = :temperature, max_tokens = :max_tokens "
                    "WHERE id = 1"
                ),
                snap,
            )
            db.commit()


@pytest.fixture(scope="module")
def llm_state_sandbox():
    """Snapshot/restore `settings_llm` autour d'un module de tests.

    Usage dans un module :
        pytestmark = pytest.mark.usefixtures("llm_state_sandbox")

    Les mutations PUT /settings/llm effectuées pendant les tests
    peuvent ensuite être « destructrices » sans crainte — l'état est
    restauré à la fin du module. **Préférer** cette fixture à un test
    de cleanup explicite (qui ne se déclenche pas en cas de crash).
    """
    with _snapshot_llm_state():
        yield


@pytest.fixture(scope="session", autouse=True)
def _purge_test_projects_after_session():
    """Hygiène. Ne touche QUE les projets dont le nom/id commence par un
    préfixe de test connu. Jamais les seeds (idf-t3-2026, etc.)."""
    yield
    base = os.environ.get("BC4_API_BASE")
    email = os.environ.get("BC4_ADMIN_EMAIL")
    pw = os.environ.get("BC4_ADMIN_PASSWORD")
    if not base or not email or not pw:
        return
    try:
        with httpx.Client(base_url=base.rstrip("/"), timeout=20.0) as c:
            r = c.post("/auth/login", json={"email": email, "password": pw})
            if r.status_code != 200:
                return
            tok = r.json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            lst = c.get("/projects", headers=h).json()
            for p in lst or []:
                name = p.get("name", "")
                pid = p.get("id", "")
                if any(name.startswith(pfx) or pid.startswith(pfx) for pfx in _TEST_NAME_PATTERNS):
                    c.delete(f"/projects/{pid}", headers=h)
    except Exception:
        # Hygiène best-effort : jamais une raison de faire échouer la session.
        pass
