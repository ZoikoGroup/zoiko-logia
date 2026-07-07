# Settings loader (env vars, tenant defaults, provider keys) - see ZoikoLogia_Back_End_Architecture_Specification
import os
from pathlib import Path
from functools import lru_cache


class Settings:
    """Application configuration loaded from environment variables.

    Falls back to SQLite for local development when DATABASE_URL is not set.
    LLM provider keys are optional — the safety service operates independently
    of model generation and does not require them.
    """

    def __init__(self) -> None:
        # ── Database ────────────────────────────────────────────────────────
        self.DATABASE_URL: str = os.getenv(
            "DATABASE_URL",
            f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'zoikologia.db'}",
        )

        # ── Authentication ──────────────────────────────────────────────────
        self.JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
        self.OIDC_ISSUER_URL: str = os.getenv("OIDC_ISSUER_URL", "")
        self.OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "")
        self.OIDC_CLIENT_SECRET: str = os.getenv("OIDC_CLIENT_SECRET", "")

        # ── LLM Providers (used by Model Gateway, NOT by Safety Service) ───
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
        self.ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
        self.AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")

        # ── Infrastructure ──────────────────────────────────────────────────
        self.VECTOR_INDEX_URL: str = os.getenv("VECTOR_INDEX_URL", "")
        self.OBJECT_STORAGE_URL: str = os.getenv("OBJECT_STORAGE_URL", "")
        self.CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "")

        # ── Safety Service Tuning ───────────────────────────────────────────
        self.CLASSIFIER_CONFIDENCE_THRESHOLD: float = float(
            os.getenv("CLASSIFIER_CONFIDENCE_THRESHOLD", "0.70")
        )
        self.SAFETY_OVERRIDE_MAX_HOURS: int = int(
            os.getenv("SAFETY_OVERRIDE_MAX_HOURS", "72")
        )

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
