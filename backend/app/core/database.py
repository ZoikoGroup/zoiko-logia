from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from collections.abc import AsyncGenerator
from typing import Generator

from app.core.config import get_settings
from app.core.security import decode_access_token

settings = get_settings()


def _normalize_scheme(url: str) -> str:
    """postgres:// is a legacy alias for postgresql:// — normalize it first
    so the two driver-specific helpers below only need to handle one scheme."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def to_async_url(url: str) -> str:
    """Normalize a bare postgresql:// URL (what Supabase's own dashboard
    hands you by default) into the asyncpg form create_async_engine
    requires. Without this, a correctly-copied Supabase connection string
    still fails at import time with "the asyncio extension requires an
    async driver" — SQLAlchemy's async engine doesn't default a driver-less
    scheme to asyncpg the way the sync engine defaults it to psycopg2."""
    url = _normalize_scheme(url)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def to_sync_url(url: str) -> str:
    """Mirrors to_async_url for the sync engine (Safety Service): collapses
    any of sqlite+aiosqlite / postgres / postgresql+asyncpg down to the sync
    driver each dialect uses (pysqlite / psycopg2)."""
    url = _normalize_scheme(url)
    if url.startswith("sqlite+aiosqlite://"):
        return "sqlite://" + url[len("sqlite+aiosqlite://"):]
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg2://" + url[len("postgresql+asyncpg://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


# Sync DB support for Safety Domain
sync_db_url = to_sync_url(settings.DATABASE_URL)
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
async_engine = create_async_engine(to_async_url(settings.DATABASE_URL), echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Request-time engine — deliberately separate from async_engine. Postgres
# RLS always exempts superusers and (without FORCE) table owners; since
# async_engine's role owns these tables and is a superuser in this Docker
# setup, request traffic must go through a distinct, non-superuser role for
# RLS to actually apply. Falls back to the same URL when APP_DATABASE_URL
# isn't set (SQLite, or a Postgres instance without the low-priv role).
request_engine = create_async_engine(to_async_url(settings.APP_DATABASE_URL or settings.DATABASE_URL), echo=False)
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
    the session for Postgres RLS (RG-02): sets app.tenant_id from the
    caller's JWT, so the sources/source_versions RLS policies enforce
    isolation even if a query forgets to filter by tenant_id itself.

    Uses is_local=false (session-scoped), not is_local=true (SET LOCAL,
    transaction-scoped) — a single request commonly spans multiple
    transactions (every audit event write commits), and a transaction-local
    setting is wiped by the very first of those commits, silently making
    every RLS-protected query afterwards see zero rows.

    Session scope persists on the underlying pooled connection beyond this
    request, though, so every code path here — including "no valid token" —
    must explicitly set it (even to ''), never skip the call. Skipping it
    when tenant_id is falsy would leave whatever a *previous* request left
    on that same pooled connection in effect for this one."""
    async with RequestSessionLocal() as session:
        if not settings.is_sqlite:
            tenant_id = _tenant_from_request(request) or ""
            # set_config(..., false) accepts a bound parameter, unlike SET,
            # whose grammar takes a literal, not a placeholder — binding
            # tenant_id directly into SET would require unsafe string
            # formatting. Always called, even with "", so a connection
            # reused from the pool never carries over a prior request's
            # tenant_id into a request that has none.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id}
            )
        yield session

