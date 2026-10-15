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
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:8080",
        alias="BC4_CORS_ORIGINS",
    )

    # Auth (B2). Le secret est OBLIGATOIRE — l'app refuse de démarrer sans.
    # Un garde qui s'auto-skippe sans secret ne garde rien.
    jwt_secret: str = Field(..., alias="BC4_JWT_SECRET")
    jwt_ttl_min: int = Field(60, alias="BC4_JWT_TTL_MIN")
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

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()  # fail-fast if DSN missing — a silent-skipping guard guards nothing
