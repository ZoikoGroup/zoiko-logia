from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from collections.abc import AsyncGenerator
from typing import Generator

from app.core.config import get_settings
from app.core.security import decode_access_token

settings = get_settings()

# Sync DB support for Safety Domain (replaces async driver prefix if present)
sync_db_url = (
    settings.DATABASE_URL
    .replace("sqlite+aiosqlite://", "sqlite://")
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
)
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

# Async DB support for other main domains. This connection stays bound to
# DATABASE_URL (the superuser role in Postgres) since it's also what
# main.py's lifespan uses for schema creation/migrations, and what the
# one-shot seed scripts (scripts/seed_dev_user.py, ingest_reference_sources.py)
# import directly — those need to write rows unconstrained by RLS.
async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Request-time engine — deliberately separate from async_engine. Postgres
# RLS always exempts superusers and (without FORCE) table owners; since
# async_engine's role owns these tables and is a superuser in this Docker
# setup, request traffic must go through a distinct, non-superuser role for
# RLS to actually apply. Falls back to the same URL when APP_DATABASE_URL
# isn't set (SQLite, or a Postgres instance without the low-priv role).
request_engine = create_async_engine(settings.APP_DATABASE_URL or settings.DATABASE_URL, echo=False)
RequestSessionLocal = async_sessionmaker(request_engine, expire_on_commit=False)

def _tenant_from_request(request: Request) -> str | None:
    """Pull tenant_id straight off the caller's JWT, without a DB round-trip
    or a dependency on get_current_user (which itself depends on get_db —
    depending on it here would be circular)."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return None
    payload = decode_access_token(token)
    return payload.tenant_id if payload else None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Async session dependency for core domain endpoints. Also tenant-scopes
    the session for Postgres RLS (RG-02): SET LOCAL app.tenant_id from the
    caller's JWT, so the sources/source_versions RLS policies enforce
    isolation even if a query forgets to filter by tenant_id itself."""
    async with RequestSessionLocal() as session:
        if not settings.is_sqlite:
            tenant_id = _tenant_from_request(request)
            if tenant_id:
                # set_config(..., true) == SET LOCAL, but (unlike SET) accepts
                # a bound parameter — SET's grammar takes a literal, not a
                # placeholder, so binding tenant_id directly into SET would
                # require unsafe string formatting.
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id}
                )
        yield session

