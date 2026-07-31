from functools import lru_cache
from pathlib import Path

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
_BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_BACKEND_ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_BACKEND_ENV_FILE, extra="ignore")

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
    LOCAL_VECTOR_STORE_DIR: str = "./vector_store"
    OBJECT_STORAGE_URL: str = ""
    CELERY_BROKER_URL: str = ""

    # ── Live External Data Sources (app/domains/live_sources/) ──────────
    # World Bank Open Data — keyless public API, no key/secret needed.
    WORLD_BANK_API_BASE_URL: str = "https://api.worldbank.org/v2"
    # ONS (Office for National Statistics) — keyless. UK CPIH index.
    ONS_API_BASE_URL: str = "https://api.beta.ons.gov.uk/v1"
    # Bank of England IADB — keyless. UK Bank Rate.
    BANK_OF_ENGLAND_API_BASE_URL: str = "https://www.bankofengland.co.uk/boeapps/database"
    # Frankfurter — keyless. FX rates. Points at the new host directly;
    # the historical api.frankfurter.app now 301-redirects here (confirmed
    # live) — see connectors/frankfurter.py.
    FRANKFURTER_API_BASE_URL: str = "https://api.frankfurter.dev/v1"
    # FRED (St. Louis Fed) — needs a free API key. Register at
    # https://fredaccount.stlouisfed.org/apikeys (see connectors/fred.py).
    # Also used by app/domains/reference_data's own FRED adapter below —
    # same field, one declaration, shared by both.
    FRED_API_BASE_URL: str = "https://api.stlouisfed.org/fred"
    FRED_API_KEY: str = ""
    # SEC EDGAR — keyless, but requires a real contact identifier in the
    # User-Agent header or requests are blocked (confirmed live). Set this
    # to "YourApp your-real-email@example.com", not a placeholder.
    SEC_EDGAR_API_BASE_URL: str = "https://data.sec.gov"
    SEC_EDGAR_USER_AGENT: str = ""
    # Companies House — needs a free API key. Register at
    # https://developer.company-information.service.gov.uk/
    COMPANIES_HOUSE_API_BASE_URL: str = "https://api.company-information.service.gov.uk"
    COMPANIES_HOUSE_API_KEY: str = ""
    # OECD — keyless. Corporate income tax rate (see connectors/oecd.py).
    OECD_API_BASE_URL: str = "https://sdmx.oecd.org/public/rest"
    # GLEIF — keyless. LEI-registry company lookup fallback for every
    # jurisdiction outside US/UK (see connectors/gleif.py).
    GLEIF_API_BASE_URL: str = "https://api.gleif.org/api/v1"
    # ECB Data Portal SDMX API — keyless official euro-area statistics.
    ECB_API_BASE_URL: str = "https://data-api.ecb.europa.eu/service"
    # IMF DataMapper API — keyless official macroeconomic indicators.
    IMF_API_BASE_URL: str = "https://www.imf.org/external/datamapper/api/v2"
    # European Commission VIES REST facade — keyless VAT-number validation.
    VIES_API_BASE_URL: str = "https://ec.europa.eu/taxation_customs/vies/rest-api"
    # Phase 2 — official legislation and procurement search.
    CELLAR_SPARQL_URL: str = "https://publications.europa.eu/webapi/rdf/sparql"
    LEGISLATION_GOV_UK_BASE_URL: str = "https://www.legislation.gov.uk"
    TED_API_BASE_URL: str = "https://api.ted.europa.eu/v3"
    SAM_GOV_OPPORTUNITIES_URL: str = "https://api.sam.gov/opportunities/v2/search"
    SAM_GOV_API_KEY: str = ""
    # Phase 3 — official sanctions snapshots. EU distribution URLs can
    # change independently of the catalogue; keep that URL configurable.
    OFAC_SDN_XML_URL: str = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
    UN_SANCTIONS_XML_URL: str = "https://scsanctions.un.org/resources/xml/en/name/consolidated.xml"
    UK_SANCTIONS_CSV_URL: str = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
    EU_SANCTIONS_CSV_URL: str = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content"
    SANCTIONS_SNAPSHOT_TTL_SECONDS: int = 3600
    SANCTIONS_MAX_DOWNLOAD_BYTES: int = 75_000_000
    SANCTIONS_SNAPSHOT_DIR: str = "./data/live_sources"
    SANCTIONS_ALLOW_INLINE_REFRESH: bool = False
    LIVE_SOURCE_HTTP_TIMEOUT_SECONDS: float = 20.0
    LIVE_SOURCE_MAX_ATTEMPTS: int = 2
    LIVE_SOURCE_RETRY_BACKOFF_SECONDS: float = 0.25
    # Macro indicators (GDP/inflation) update quarterly/annually at most —
    # 6h TTL avoids re-fetching World Bank on every request without risking
    # meaningfully stale figures relative to this data's own update cadence.
    LIVE_SOURCE_CACHE_TTL_SECONDS: int = 21600

    # ── External reference data (app/domains/reference_data/) ───────────
    # Public, no-auth API — no key needed, but the base URL lives here
    # rather than hardcoded in the adapter so it can be repointed (a new
    # API version, a mirror, a test double) without a code change.
    TREASURY_FISCAL_DATA_BASE_URL: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1"

    # Keyed, metered API (free tier: 1,000 req/month, 20/min) — unlike
    # Treasury, this requires a real secret key. Plain str like every other
    # key in this Settings class (no field here uses SecretStr) — never
    # place the raw value into any audit payload/log/exception message (see
    # app/domains/reference_data/adapters/payroll_tax_adapter.py).
    PAYROLL_TAX_API_BASE_URL: str = "https://payrolltaxapi.com/v1"
    PAYROLL_TAX_API_KEY: str = ""

    # US Census Bureau API (American Community Survey) — free with
    # registration, keyed via query param rather than a header.
    CENSUS_API_BASE_URL: str = "https://api.census.gov/data"
    CENSUS_API_KEY: str = ""

    # US Bureau of Labor Statistics Public Data API (CPI/inflation) — free
    # without registration at low rate limits, registration raises them.
    BLS_API_BASE_URL: str = "https://api.bls.gov/publicAPI/v2"
    BLS_API_KEY: str = ""

    # US Bureau of Economic Analysis API (GDP / NIPA national accounts) —
    # free with registration, keyed via a query param like Census.
    BEA_API_BASE_URL: str = "https://apps.bea.gov/api/data"
    BEA_API_KEY: str = ""

    # US Government Publishing Office GovInfo API — free with registration,
    # keyed via a query param. Used for on-demand lookup of specific 26 CFR
    # (Internal Revenue) regulation sections — the actual regulatory text,
    # not a numeric series like the sources above.
    GOVINFO_API_BASE_URL: str = "https://api.govinfo.gov"
    GOVINFO_API_KEY: str = ""

    # Federal Register API — fully public, no key/registration required.
    # Used for on-demand lookup of a specific document by its document
    # number (e.g. "2026-13925") when a query names one.
    FEDERAL_REGISTER_API_BASE_URL: str = "https://www.federalregister.gov/api/v1"

    # eCFR (Electronic Code of Federal Regulations) API — fully public, no
    # key required. Same 26 CFR section-lookup job as GovInfo above, kept
    # alongside it rather than replacing it (comprehensive data collection
    # is the explicit goal here) — eCFR reflects the current amended text
    # rather than a static annual edition.
    ECFR_API_BASE_URL: str = "https://www.ecfr.gov/api/versioner/v1"

    # SEC EDGAR public data via app/domains/reference_data's own adapter —
    # distinct field names from SEC_EDGAR_API_BASE_URL/SEC_EDGAR_USER_AGENT
    # above (that pair belongs to live_sources/connectors/sec_edgar.py);
    # kept as two separate declarations rather than unified, since renaming
    # either would break whichever module already depends on its own name.
    SEC_DATA_API_BASE_URL: str = "https://data.sec.gov"
    SEC_USER_AGENT: str = ""

    # Congress.gov API — keyed public legislative data.
    CONGRESS_API_BASE_URL: str = "https://api.congress.gov/v3"
    CONGRESS_API_KEY: str = ""

    # Regulations.gov API — keyed federal rulemaking and docket data.
    REGULATIONS_GOV_API_BASE_URL: str = "https://api.regulations.gov/v4"
    REGULATIONS_GOV_API_KEY: str = ""

    # Optional commercial ZIP-level tax lookup. Keep the URL empty until a
    # provider endpoint and its licence have been confirmed.
    ZIPTAX_API_BASE_URL: str = ""
    ZIPTAX_API_KEY: str = ""

    # Governed web discovery. These services locate candidate authority
    # pages; their snippets are never themselves treated as approved answer
    # evidence. Callers must enforce the allowlist and pass fetched content
    # through the normal source-governance workflow before composition.
    TAVILY_API_BASE_URL: str = "https://api.tavily.com"
    TAVILY_API_KEY: str = ""
    SERP_API_BASE_URL: str = "https://serpapi.com/search.json"
    # The project uses SERP_API_KEY in .env (rather than SerpAPI's common
    # SERPAPI_API_KEY spelling); keep that exact name so the saved key loads.
    SERP_API_KEY: str = ""
    PROFESSIONAL_SEARCH_ALLOWED_DOMAINS: list[str] = [
        "irs.gov",
        "sec.gov",
        "pcaobus.org",
        "fasb.org",
        "gao.gov",
        "congress.gov",
        "govinfo.gov",
        "ecfr.gov",
        "federalregister.gov",
        "aicpa-cima.com",
    ]

    # ── Safety Service Tuning ───────────────────────────────────────────
    # cross-encoder/nli-distilroberta-base's actual score distribution runs
    # much lower than the original 0.65 assumed — even unambiguous accounting
    # questions ("What is the accrual basis of accounting?") score ~0.51, so
    # 0.65 meant every query fell back to CLASSIFICATION_UNCERTAIN regardless
    # of content. 0.35 sits below the clear-question range observed in
    # testing while still catching genuinely vague input.
    CLASSIFIER_CONFIDENCE_THRESHOLD: float = 0.35
    # Per-tier calibration. ZERO has the strictest threshold because an
    # uncertain substantive query must never fail open as harmless chatter.
    # HIGH is intentionally permissive: conservative over-classification is
    # safer than missing a professional-advice query.
    CLASSIFIER_ZERO_CONFIDENCE_THRESHOLD: float = 0.50
    CLASSIFIER_LOW_CONFIDENCE_THRESHOLD: float = 0.35
    CLASSIFIER_MEDIUM_CONFIDENCE_THRESHOLD: float = 0.35
    CLASSIFIER_HIGH_CONFIDENCE_THRESHOLD: float = 0.30
    # LLM classifier rollout is controlled through process-environment flags
    # read by risk_safety/llm_classifier.py: off | fallback | shadow.
    # It defaults off, and any provider failure takes the conservative path.
    SAFETY_OVERRIDE_MAX_HOURS: int = 72

    # Cosine-similarity threshold for infer_category()'s embedding-based
    # fallback (app/orchestration/retrieve.py) — same empirical-testing
    # discipline as CLASSIFIER_CONFIDENCE_THRESHOLD above. Measured against
    # the real installed all-MiniLM-L6-v2 model with 13 generalization
    # paraphrases (not in the example bank) across all 10 categories plus 2
    # deliberately out-of-scope queries (FRS 102, PCAOB AS 2201): true
    # positives scored 0.513-0.777, true negatives scored 0.318-0.327 — a
    # clean gap. 0.45 sits comfortably in that gap.
    CATEGORY_SEMANTIC_THRESHOLD: float = 0.45

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:

    return Settings()
