from functools import lru_cache
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings' env_file=".env" below only populates this Settings
# class's own fields — it never touches the real process environment. But
# several modules (groq_adapter.py, risk_classifier.py's ENABLE_ML_CLASSIFIER
# check, etc.) read os.getenv(...)/os.environ.get(...) directly for
# flags/keys that have no Settings field. Without this, those reads only
# ever see values already present in the OS/container environment
# (docker-compose's `environment:`/`env_file:` inject there directly) — a
# plain local `uvicorn` run reading only backend/.env would silently leave
# them unset, disabling the ML classifier and real LLM providers with no
# error. load_dotenv() populates os.environ from .env without overriding
# anything already set there.
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
    # Bound both establishing a database connection and waiting for one from
    # the pool. A remote pooler/DNS incident must fail quickly enough for the
    # API to return a controlled 503 instead of consuming the complete Ask
    # Kriton request deadline.
    DB_CONNECT_TIMEOUT_SECONDS: int = 10
    DB_POOL_TIMEOUT_SECONDS: float = 10.0

    # ── CORS ─────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── Supabase Auth ────────────────────────────────────────────────────
    # Backend verifies Supabase-issued access tokens (JWKS) and, for the
    # service-role-only Admin API calls (creating auth users, writing
    # app_metadata), never exposed to the frontend.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # When true, startup hard-fails (RuntimeError) if Supabase auth isn't
    # configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY unset or empty).
    # Staging/prod should set this so a missing service-role key fails the
    # deploy loudly at the gateway instead of surfacing later as a cascade of
    # 401s plus silently-skipped user seeding. Local/dev leave unset — the
    # soft warning + skip-seeding behavior is intentional for plain-SQLite /
    # frontend-only work.
    REQUIRE_SUPABASE_CONFIG: bool = False

    # ── LLM Providers ───────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""

    # ── Infrastructure ──────────────────────────────────────────────────
    OBJECT_STORAGE_URL: str = ""
    CELERY_BROKER_URL: str = ""

    # ── Safety Service Tuning ───────────────────────────────────────────
    # cross-encoder/nli-distilroberta-base's actual score distribution runs
    # much lower than the original 0.65 assumed — even unambiguous accounting
    # questions ("What is the accrual basis of accounting?") score ~0.51, so
    # 0.65 meant every query fell back to CLASSIFICATION_UNCERTAIN regardless
    # of content. 0.35 sits below the clear-question range observed in
    # testing while still catching genuinely vague input.
    CLASSIFIER_CONFIDENCE_THRESHOLD: float = 0.35
    SAFETY_OVERRIDE_MAX_HOURS: int = 72
    # Hard ceiling for the complete Ask Kriton pipeline. Keep this below the
    # browser's transport timeout so the API can return a controlled 504 (or a
    # terminal stream error) instead of letting the browser sever the socket.
    ASK_KRITON_TIMEOUT_SECONDS: float = 105.0
    # One ceiling for the combined FX/statistics/market-data fan-out. Individual
    # provider retry policies must not add up beyond this request-level budget.
    LIVE_DATA_TIMEOUT_SECONDS: float = 12.0

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:

    return Settings()
