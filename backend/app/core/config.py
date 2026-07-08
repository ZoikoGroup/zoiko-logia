from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"

    # ── Authentication & CORS ───────────────────────────────────────────
    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── OIDC (Safety Auth Integration) ──────────────────────────────────
    OIDC_ISSUER_URL: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""

    # ── LLM Providers ───────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""

    # ── Infrastructure ──────────────────────────────────────────────────
    VECTOR_INDEX_URL: str = ""
    OBJECT_STORAGE_URL: str = ""
    CELERY_BROKER_URL: str = ""

    # ── Safety Service Tuning ───────────────────────────────────────────
    CLASSIFIER_CONFIDENCE_THRESHOLD: float = 0.65
    SAFETY_OVERRIDE_MAX_HOURS: int = 72

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:

    return Settings()
