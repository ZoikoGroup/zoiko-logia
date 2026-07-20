"""
Seed the LiveSourceProvider registry rows — required once per environment
before ENABLE_LIVE_SOURCES=1 queries will find an ACTIVE provider record
(see app/domains/massarius/license_gate.py's _fetch_live_provider_fields()).
Idempotent: safe to re-run; each provider is skipped if already present.

Run:
    python backend/scripts/seed_live_source_provider.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.db.base import Base
from app.domains.live_sources.models import LiveSourceProvider

settings = get_settings()

# (provider_key, display_name, base_url, category, auth_mode, api_key_env_var)
# — all "primary" authority (official government/intergovernmental sources,
# or in Companies House/SEC EDGAR's case, the statutory company registry).
PROVIDERS = [
    ("world_bank", "World Bank Open Data", settings.WORLD_BANK_API_BASE_URL,
     "macro-economic-data", "none", None),
    ("ons", "ONS (Office for National Statistics)", settings.ONS_API_BASE_URL,
     "macro-economic-data", "none", None),
    ("bank_of_england", "Bank of England IADB", settings.BANK_OF_ENGLAND_API_BASE_URL,
     "macro-economic-data", "none", None),
    ("frankfurter", "Frankfurter (ECB exchange rates)", settings.FRANKFURTER_API_BASE_URL,
     "fx-rates", "none", None),
    ("fred", "FRED (Federal Reserve Economic Data)", settings.FRED_API_BASE_URL,
     "macro-economic-data", "api_key", "FRED_API_KEY"),
    ("sec_edgar", "SEC EDGAR Company Facts", settings.SEC_EDGAR_API_BASE_URL,
     "company-financials", "none", None),
    ("companies_house", "Companies House", settings.COMPANIES_HOUSE_API_BASE_URL,
     "company-financials", "api_key", "COMPANIES_HOUSE_API_KEY"),
]


async def seed_provider(
    db, *, provider_key: str, display_name: str, base_url: str,
    category: str, auth_mode: str, api_key_env_var: str | None,
) -> None:
    existing = await db.execute(
        select(LiveSourceProvider).where(LiveSourceProvider.provider_key == provider_key)
    )
    if existing.scalar_one_or_none() is not None:
        print(f"LiveSourceProvider '{provider_key}' already seeded, skipping.")
        return

    db.add(LiveSourceProvider(
        provider_key=provider_key,
        display_name=display_name,
        category=category,
        base_url=base_url,
        auth_mode=auth_mode,
        api_key_env_var=api_key_env_var,
        licence_state="permitted",
        authority_level="primary",
        is_tenant_private=False,
        status="ACTIVE",
    ))
    await db.commit()
    print(f"Seeded LiveSourceProvider '{provider_key}'.")


async def seed() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for provider_key, display_name, base_url, category, auth_mode, api_key_env_var in PROVIDERS:
            await seed_provider(
                db, provider_key=provider_key, display_name=display_name, base_url=base_url,
                category=category, auth_mode=auth_mode, api_key_env_var=api_key_env_var,
            )


if __name__ == "__main__":
    asyncio.run(seed())
