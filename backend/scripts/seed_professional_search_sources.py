"""Idempotently register the governed Tavily and SerpAPI connectors."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.domains.identity.models import User
from scripts.seed_dev_user import DEMO_EMAIL, seed_professional_search_sources


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one()
        await seed_professional_search_sources(db, user)


if __name__ == "__main__":
    asyncio.run(seed())
