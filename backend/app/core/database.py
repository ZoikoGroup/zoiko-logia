from fastapi import Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from collections.abc import AsyncGenerator
from typing import Generator

from app.core.config import get_settings
from app.core.supabase_auth import verify_token

settings = get_settings()


def _pool_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
    }


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

engine = create_engine(
    sync_db_url, connect_args=connect_args, pool_pre_ping=True,
    **_pool_options(sync_db_url),
)
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
async_database_url = to_async_url(settings.DATABASE_URL)
async_engine = create_async_engine(
    async_database_url, echo=False, pool_pre_ping=True,
    **_pool_options(async_database_url),
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Request-time engine — deliberately separate from async_engine. Postgres
# RLS always exempts superusers and (without FORCE) table owners; since
# async_engine's role owns these tables and is a superuser in this Docker
# setup, request traffic must go through a distinct, non-superuser role for
# RLS to actually apply. Falls back to the same URL when APP_DATABASE_URL
# isn't set (SQLite, or a Postgres instance without the low-priv role).
#
# pool_pre_ping=True on both engines (matching the sync engine above) —
# confirmed necessary the hard way: a pooled connection to the remote
# Supabase host went stale mid-session and the next request crashed the
# whole server with asyncpg.exceptions.ConnectionDoesNotExistError instead
# of transparently reconnecting. pre_ping issues a lightweight check before
# handing out a pooled connection and replaces it silently if it's dead —
# adds negligible overhead on a healthy connection, and is exactly what
# would have caught this.
request_database_url = to_async_url(settings.APP_DATABASE_URL or settings.DATABASE_URL)
request_engine = create_async_engine(
    request_database_url, echo=False, pool_pre_ping=True,
    **_pool_options(request_database_url),
)
RequestSessionLocal = async_sessionmaker(request_engine, expire_on_commit=False)

def _identity_from_request(request: Request) -> tuple[str, str]:
    """Pull (user_id, tenant_id) straight off the caller's Supabase JWT,
    without a DB round-trip or a dependency on get_current_user (which
    itself depends on get_db — depending on it here would be circular).
    tenant_id comes out of app_metadata, which the backend sets via the
    Supabase Admin API at /auth/provision time (see supabase_admin.py) —
    never client-writable."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return "", ""
    claims = verify_token(token)
    if claims is None:
        return "", ""
    return claims.sub, claims.tenant_id


# Real gap (2026-08-06): the original approach set app.tenant_id/app.user_id
# ONCE per request with is_local=false (session-scoped) specifically to
# survive multiple commits within one request (every audit event write is
# its own transaction; a transaction-local SET LOCAL would be wiped by the
# first of those, silently making every RLS-protected query afterwards see
# zero rows). But APP_DATABASE_URL points at Supabase's transaction-pooling
# port (PgBouncer) — in transaction-pooling mode, PgBouncer can hand back a
# DIFFERENT physical Postgres backend connection for each statement within
# what the app considers "the same session," so a session-scoped
# set_config() call and the query it's meant to protect can silently land
# on two different backend connections. When that happens app.tenant_id
# reads back unset and RLS blocks every row on that table — including
# fully public ones — which is exactly the intermittent "0 eligible
# sources" failures observed live (confirmed by instrumenting get_db(): the
# resolved tenant_id was identical, empty, across both a request that
# succeeded and three that failed back-to-back).
#
# Fixed by using is_local=true (SET LOCAL, transaction-scoped — safe from
# leaking into a different logical request on a reused pooled connection)
# AND re-applying it at the start of EVERY transaction within the request,
# not just once. Session.info survives across commits on the same
# AsyncSession (unlike a transaction-local Postgres setting), so it's used
# to stash the identity once here; the after_begin listener below then
# re-issues SET LOCAL on whatever physical connection PgBouncer actually
# hands out for each new transaction — solving both the original multi-
# commit problem AND the pooling mismatch at the same time.
def _apply_rls_identity(session: Session, transaction, connection) -> None:
    if "app_tenant_id" not in session.info:
        return
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": session.info["app_tenant_id"]},
    )
    connection.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": session.info["app_user_id"]},
    )


event.listens_for(Session, "after_begin")(_apply_rls_identity)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Async session dependency for core domain endpoints. Also identity-
    scopes the session for Postgres RLS: sets app.tenant_id (RG-02,
    sources/source_versions isolation) and app.user_id (users table's
    self-row RLS policy) from the caller's verified Supabase token, so
    RLS policies enforce isolation even if a query forgets to filter
    itself.

    The actual SET LOCAL calls happen in _apply_rls_identity above, fired
    by the after_begin ORM event on every new transaction this session
    opens — see that function's docstring for why. This function's job is
    only to stash the resolved identity on session.info before any query
    runs, including "no valid token" (stashed as '', never skipped —
    session.info is per-AsyncSession-instance, never reused across
    requests, so there's no leftover-identity risk the way the old
    pooled-connection approach had)."""
    async with RequestSessionLocal() as session:
        if not settings.is_sqlite:
            user_id, tenant_id = _identity_from_request(request)
            session.info["app_tenant_id"] = tenant_id
            session.info["app_user_id"] = user_id
        yield session
