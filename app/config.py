from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BC4_", env_file=".env", extra="ignore")

    dsn: str = Field(..., alias="BC4_DSN")
    env: str = Field("development", alias="BC4_ENV")
    # Origines autorisées (CSV). Toujours piloté par l'env en prod ; la
    # valeur par défaut couvre les ports Vite usuels + 127.0.0.1 pour
    # lever le préflight CORS depuis le navigateur dev sans Vite proxy.
    cors_origins: str = Field(
        "http://localhost:5173,http://localhost:5174,http://localhost:8080,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:8080,"
        "https://franco-focus-forge.lovable.app,"
        "https://id-preview--a8015a08-bb84-4b94-b38f-e26461097bfa.lovable.app,"
        "https://a8015a08-bb84-4b94-b38f-e26461097bfa.lovableproject.com",
        alias="BC4_CORS_ORIGINS",
    )

    # Auth (B2). Le secret est OBLIGATOIRE — l'app refuse de démarrer sans.
    # Un garde qui s'auto-skippe sans secret ne garde rien.
    jwt_secret: str = Field(..., alias="BC4_JWT_SECRET")
    # Analytics sessions routinely exceed one hour.  Keep the deployment
    # override available, but make the operational default a workday so
    # an active KPI exploration does not fail midway with an avoidable 401.
    jwt_ttl_min: int = Field(480, alias="BC4_JWT_TTL_MIN")
    # Compte admin seedé idempotent au premier démarrage (idempotent sur email).
    # Si l'un des deux est absent, le seed admin est sauté — pas d'invention.
    admin_email: str | None = Field(default=None, alias="BC4_ADMIN_EMAIL")
    admin_password: str | None = Field(default=None, alias="BC4_ADMIN_PASSWORD")
    # Compte DEMO (lecteur/ingenieur selon besoin). Seed idempotent au
    # premier démarrage ; si l'un des deux est absent, le seed démo est
    # sauté (pas d'invention). Rôle par défaut `ingenieur` — override
    # possible par `BC4_DEMO_ROLE`.
    demo_email: str | None = Field(default=None, alias="BC4_DEMO_EMAIL")
    demo_password: str | None = Field(default=None, alias="BC4_DEMO_PASSWORD")
    demo_role: str = Field(default="ingenieur", alias="BC4_DEMO_ROLE")
    # 0.89.4 — gate démo seed. Défaut 0 (= aucun projet démo ni
    # measurement_points/rrc_observations ni table users dépréciée).
    # Mettre `BC4_SEED_DEMO=1` dans .env pour une installation de
    # démonstration. Ne RÉACTIVE PAS les comptes BC4_DEMO_* (ceux-ci
    # restent gatés par leur propre BC4_DEMO_EMAIL/PASSWORD).
    seed_demo: bool = Field(default=False, alias="BC4_SEED_DEMO")

    # Import queue (0.92.0 candidate).  Processes are required here: NMF
    # parsing is CPU-bound Python and therefore does not benefit from threads.
    import_workers_max: int = Field(6, ge=1, le=6, alias="BC4_IMPORT_WORKERS_MAX")
    import_reserved_mb: int = Field(4096, ge=0, alias="BC4_IMPORT_RESERVED_MB")
    import_memory_margin_mb: int = Field(512, ge=1, alias="BC4_IMPORT_MEMORY_MARGIN_MB")
    import_batch_size: int = Field(5000, ge=100, le=50000, alias="BC4_IMPORT_BATCH_SIZE")
    import_finalize_batch_size: int = Field(
        500, ge=100, le=5000, alias="BC4_IMPORT_FINALIZE_BATCH_SIZE"
    )
    # Affine RSS estimate: base_mb + slope_mb_per_mib * file_size_mib.
    # A fixed base avoids the severe over-reservation caused by a pure ratio.
    import_memory_base_mb_deep: float = Field(
        1370.0, ge=0, alias="BC4_IMPORT_MEMORY_BASE_MB_DEEP"
    )
    import_memory_slope_mb_per_mib_deep: float = Field(
        46.0, gt=0, alias="BC4_IMPORT_MEMORY_SLOPE_MB_PER_MIB_DEEP"
    )
    import_memory_base_mb_light: float = Field(
        1370.0, ge=0, alias="BC4_IMPORT_MEMORY_BASE_MB_LIGHT"
    )
    import_memory_slope_mb_per_mib_light: float = Field(
        46.0, gt=0, alias="BC4_IMPORT_MEMORY_SLOPE_MB_PER_MIB_LIGHT"
    )
    import_memory_model_source: str = Field(
        "BC1 2026-10-28 disposable Deep/Light NMF 5078863..17040816 bytes; "
        "conservative envelope checked against supplied production reference "
        "64 MiB / 4.2 GiB",
        alias="BC4_IMPORT_MEMORY_MODEL_SOURCE",
    )
    spatial_fix_max_gap_s: float = Field(
        1.0, ge=0.0, alias="BC4_SPATIAL_FIX_MAX_GAP_S"
    )

    # LLM (0.16.0) — précédence : DB (settings_llm) > env ci-dessous.
    # BC4_LLM_SECRET_KEY : clé Fernet pour chiffrer l'api_key au repos.
    # Si absente, GET fonctionne (api_key_set reflète la DB), mais PUT
    # d'une clé lèvera (fail-fast, pas de stockage en clair déguisé).
    llm_secret_key: str | None = Field(default=None, alias="BC4_LLM_SECRET_KEY")
    llm_provider: str = Field(default="", alias="BC4_LLM_PROVIDER")
    llm_base_url: str = Field(default="", alias="BC4_LLM_BASE_URL")
    llm_model: str = Field(default="", alias="BC4_LLM_MODEL")
    llm_api_key: str = Field(default="", alias="BC4_LLM_API_KEY")
    llm_enabled: bool = Field(default=False, alias="BC4_LLM_ENABLED")
    # 0.27.0 — model_loop (boucle outils, pas cher) + cap journalier.
    # Fallback env si DB vide ; DB prévaut si posée.
    llm_model_loop: str = Field(default="", alias="BC4_LLM_MODEL_LOOP")
    llm_daily_cap_usd: float = Field(default=0.0, alias="BC4_LLM_DAILY_CAP_USD")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()  # fail-fast if DSN missing — a silent-skipping guard guards nothing
