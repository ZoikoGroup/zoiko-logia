"""
Seed the World Bank LiveSourceProvider registry row — required once per
environment before ENABLE_LIVE_SOURCES=1 queries will find an ACTIVE
provider record (see app/domains/massarius/license_gate.py's
_fetch_live_provider_fields()). Idempotent: safe to re-run.

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


async def seed_world_bank_provider(db) -> None:
    existing = await db.execute(
        select(LiveSourceProvider).where(LiveSourceProvider.provider_key == "world_bank")
    )
    if existing.scalar_one_or_none() is not None:
        print("LiveSourceProvider 'world_bank' already seeded, skipping.")
        return

    db.add(LiveSourceProvider(
        provider_key="world_bank",
        display_name="World Bank Open Data",
        category="macro-economic-data",
        base_url=settings.WORLD_BANK_API_BASE_URL,
        auth_mode="none",
        api_key_env_var=None,
        licence_state="permitted",
        authority_level="primary",
        is_tenant_private=False,
        status="ACTIVE",
    ))
    await db.commit()
    print("Seeded LiveSourceProvider 'world_bank'.")


async def seed() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_world_bank_provider(db)


if __name__ == "__main__":
    asyncio.run(seed())
