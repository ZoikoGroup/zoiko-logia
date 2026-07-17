from functools import lru_cache
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings' env_file=".env" below only populates this Settings
# class's own fields — it never touches the real process environment. But
# several modules (groq_adapter.py, risk_classifier.py, orchestration's
# ENABLE_RAG_EMBEDDINGS checks, etc.) read os.getenv(...)/os.environ.get(...)
# directly for flags/keys that have no Settings field. Without this, those
# reads only ever see values already present in the OS/container
# environment (docker-compose's `environment:`/`env_file:` inject there
# directly) — a plain local `uvicorn` run reading only backend/.env would
# silently leave them unset, disabling RAG retrieval, the ML classifier, and
# real LLM providers with no error. load_dotenv() populates os.environ from
# .env without overriding anything already set there.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    # Optional separate, non-superuser connection for request-time queries
    # (see app/core/database.py) — lets Postgres RLS actually apply, since
    # RLS always exempts superusers/table owners no matter what FORCE does.
    # Falls back to DATABASE_URL when unset (SQLite, or a Postgres setup
    # that hasn't provisioned the low-privilege role).
    APP_DATABASE_URL: str | None = None

    # ── CORS ─────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── OIDC (Safety Auth Integration) ──────────────────────────────────
    OIDC_ISSUER_URL: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""

    # ── Supabase Auth ────────────────────────────────────────────────────
    # Backend verifies Supabase-issued access tokens (JWKS) and, for the
    # service-role-only Admin API calls (creating auth users, writing
    # app_metadata), never exposed to the frontend.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── LLM Providers ───────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""

    # ── Infrastructure ──────────────────────────────────────────────────
    VECTOR_INDEX_URL: str = ""
    OBJECT_STORAGE_URL: str = ""
    CELERY_BROKER_URL: str = ""

    # ── Live External Data Sources (app/domains/live_sources/) ──────────
    # World Bank Open Data — keyless public API, no key/secret needed.
    WORLD_BANK_API_BASE_URL: str = "https://api.worldbank.org/v2"
    LIVE_SOURCE_HTTP_TIMEOUT_SECONDS: float = 10.0
    # Macro indicators (GDP/inflation) update quarterly/annually at most —
    # 6h TTL avoids re-fetching World Bank on every request without risking
    # meaningfully stale figures relative to this data's own update cadence.
    LIVE_SOURCE_CACHE_TTL_SECONDS: int = 21600

    # ── Safety Service Tuning ───────────────────────────────────────────
    # cross-encoder/nli-distilroberta-base's actual score distribution runs
    # much lower than the original 0.65 assumed — even unambiguous accounting
    # questions ("What is the accrual basis of accounting?") score ~0.51, so
    # 0.65 meant every query fell back to CLASSIFICATION_UNCERTAIN regardless
    # of content. 0.35 sits below the clear-question range observed in
    # testing while still catching genuinely vague input.
    CLASSIFIER_CONFIDENCE_THRESHOLD: float = 0.35
    SAFETY_OVERRIDE_MAX_HOURS: int = 72

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:

    return Settings()
