from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from collections.abc import AsyncGenerator
from typing import Generator

from app.core.config import get_settings
from app.core.supabase_auth import verify_token

settings = get_settings()

# Supabase/pgbouncer can occasionally leave a TCP connection half-open long
# enough for the operating-system timeout (~120s) to fire.  That is longer
# than Ask Kriton's entire frontend deadline.  Bound connection acquisition,
# pool checkout and individual commands so pool_pre_ping/reconnects fail fast
# and SQLAlchemy can discard the bad connection.
_ASYNC_POSTGRES_CONNECT_ARGS = {
    "timeout": 10,
    "command_timeout": 15,
}
_SYNC_POSTGRES_CONNECT_ARGS = {
    "connect_timeout": 10,
    "options": "-c statement_timeout=15000",
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
connect_args = (
    {"check_same_thread": False}
    if sync_db_url.startswith("sqlite")
    else _SYNC_POSTGRES_CONNECT_ARGS
)

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
# pool_pre_ping revalidates a pooled connection before handing it out, and
# pool_recycle drops connections older than 5 min — both needed because
# Supabase's connection pooler silently closes idle connections, and without
# these a reused-but-dead connection fails a request with
# "asyncpg ... connection is closed" (intermittent, since it only hits stale
# ones). Mirrors the sync `engine` above, which already sets pool_pre_ping.
async_engine = create_async_engine(
    to_async_url(settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=10,
    connect_args=(
        {} if settings.is_sqlite else _ASYNC_POSTGRES_CONNECT_ARGS
    ),
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Request-time engine — deliberately separate from async_engine. Postgres
# RLS always exempts superusers and (without FORCE) table owners; since
# async_engine's role owns these tables and is a superuser in this Docker
# setup, request traffic must go through a distinct, non-superuser role for
# RLS to actually apply. Falls back to the same URL when APP_DATABASE_URL
# isn't set (SQLite, or a Postgres instance without the low-priv role).
request_engine = create_async_engine(
    to_async_url(settings.APP_DATABASE_URL or settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=10,
    connect_args=(
        {} if settings.is_sqlite else _ASYNC_POSTGRES_CONNECT_ARGS
    ),
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


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Async session dependency for core domain endpoints. Also identity-
    scopes the session for Postgres RLS: sets app.tenant_id (RG-02,
    sources/source_versions isolation) and app.user_id (users table's
    self-row RLS policy) from the caller's verified Supabase token, so
    RLS policies enforce isolation even if a query forgets to filter
    itself.

    Uses is_local=false (session-scoped), not is_local=true (SET LOCAL,
    transaction-scoped) — a single request commonly spans multiple
    transactions (every audit event write commits), and a transaction-local
    setting is wiped by the very first of those commits, silently making
    every RLS-protected query afterwards see zero rows.

    Session scope persists on the underlying pooled connection beyond this
    request, though, so every code path here — including "no valid token" —
    must explicitly set both (even to ''), never skip the call. Skipping it
    when they're falsy would leave whatever a *previous* request left on
    that same pooled connection in effect for this one.

    The session is bound to ONE checked-out connection for the whole request,
    which is what makes the two settings above mean anything. They live on a
    connection, not on a session: a session normally returns its connection to
    the pool at every commit and checks one out again for the next statement,
    and a request that commits part-way — every audit write does — can be
    handed a different connection afterwards, one that never had set_config run
    on it. Every RLS-protected statement after that point then sees nothing.

    That failure is invisible on a quiet pool, because the connection just
    released is usually the one handed back. Under any concurrency it appears:
    a document upload inserted its row successfully, committed, and the very
    next UPDATE on that same row matched zero rows — the row was real, the
    policy was right, and the new connection simply had no identity on it.
    Holding one connection for the request removes the possibility."""
    async with request_engine.connect() as connection, \
            RequestSessionLocal(bind=connection) as session:
        if not settings.is_sqlite:
            user_id, tenant_id = _identity_from_request(request)
            # set_config(..., false) accepts a bound parameter, unlike SET,
            # whose grammar takes a literal, not a placeholder — binding
            # these directly into SET would require unsafe string
            # formatting. Always called, even with "", so a connection
            # reused from the pool never carries over a prior request's
            # identity into a request that has none.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id}
            )
            await session.execute(
                text("SELECT set_config('app.user_id', :user_id, false)"), {"user_id": user_id}
            )
        yield session
