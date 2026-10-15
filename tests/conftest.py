import os

import httpx
import pytest


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
        pytest.skip("BC4_ADMIN_EMAIL/BC4_ADMIN_PASSWORD manquants")
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
