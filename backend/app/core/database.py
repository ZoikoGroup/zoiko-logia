from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from collections.abc import AsyncGenerator
from typing import Generator

from app.core.config import get_settings

settings = get_settings()

# Sync DB support for Safety Domain (replaces async driver prefix if present)
sync_db_url = settings.DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
connect_args = {"check_same_thread": False} if sync_db_url.startswith("sqlite") else {}

engine = create_engine(sync_db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_sync_db() -> Generator[Session, None, None]:
    """Sync session dependency for the Safety Service endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Async DB support for other main domains
async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async session dependency for core domain endpoints."""
    async with AsyncSessionLocal() as session:
        yield session

