import asyncio
import time

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
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
    "timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
    "command_timeout": 15,
}
_SYNC_POSTGRES_CONNECT_ARGS = {
    "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
    "options": "-c statement_timeout=15000",
}


def session_is_sqlite(session) -> bool:
    """True when `session` is backed by SQLite. The RLS re-scoping
    set_config statements are Postgres-only and crash on SQLite with "no
    such function: set_config", so every caller must skip them there. Prefer
    the live session's engine dialect over settings.is_sqlite: tests build
    ad-hoc sqlite+aiosqlite engines (and pass those sessions straight into
    the domain functions) while settings.DATABASE_URL still points at the
    real Postgres URL in .env — a config-level check can't see that and
    wrongly runs set_config on the test's SQLite engine."""
    if settings.is_sqlite:
        return True
    get_bind = getattr(session, "get_bind", None)
    if get_bind is None:
        return False
    try:
        return get_bind().dialect.name == "sqlite"
    except Exception:
        return False


async def restore_request_identity(session, *, tenant_id: str, user_id: str) -> None:
    """Re-apply the request's RLS identity and commit it.

    A database timeout cancels the in-flight query, and the cancelled
    connection is replaced from the pool — one that still carries an earlier
    request's app.tenant_id. Every RLS write after that is checked against
    the wrong tenant ("new row violates row-level security policy"). Call
    this after any rollback that recovers from such a failure."""
    if session_is_sqlite(session):
        return
    await session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id})
    await session.execute(text("SELECT set_config('app.user_id', :user_id, false)"), {"user_id": user_id})
    await session.commit()


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


def _sync_engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "connect_args": _SYNC_POSTGRES_CONNECT_ARGS,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        "pool_pre_ping": True,
        # Pre-ping catches a connection the pooler closed while idle, so
        # recycling can be rarer: every new connection is a TLS handshake that
        # can hang on a flaky network.
        "pool_recycle": 900,
    }


def _async_engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    # asyncpg calls its connection-establishment option `timeout`; SQLAlchemy's
    # pool_timeout separately bounds waiting when every pooled connection is in
    # use.
    return {
        "connect_args": _ASYNC_POSTGRES_CONNECT_ARGS,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        "pool_pre_ping": True,
        # Pre-ping catches a connection the pooler closed while idle, so
        # recycling can be rarer: every new connection is a TLS handshake that
        # can hang on a flaky network.
        "pool_recycle": 900,
    }


# Sync DB support for Safety Domain
sync_db_url = to_sync_url(settings.DATABASE_URL)
engine = create_engine(sync_db_url, **_sync_engine_options(sync_db_url))
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
# pool_recycle drops connections older than 15 min — both needed because
# Supabase's connection pooler silently closes idle connections, and without
# these a reused-but-dead connection fails a request with
# "asyncpg ... connection is closed" (intermittent, since it only hits stale
# ones). Mirrors the sync `engine` above, which already sets pool_pre_ping.
async_db_url = to_async_url(settings.DATABASE_URL)
async_engine = create_async_engine(async_db_url, echo=False, **_async_engine_options(async_db_url))
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Request-time engine — deliberately separate from async_engine. Postgres
# RLS always exempts superusers and (without FORCE) table owners; since
# async_engine's role owns these tables and is a superuser in this Docker
# setup, request traffic must go through a distinct, non-superuser role for
# RLS to actually apply. Falls back to the same URL when APP_DATABASE_URL
# isn't set (SQLite, or a Postgres instance without the low-priv role).
request_db_url = to_async_url(settings.APP_DATABASE_URL or settings.DATABASE_URL)


def _request_engine_options(url: str) -> dict:
    """The request pool: connections kept, not churned, and no pre-ping.
    Every user of this pool sets the RLS identity first
    (open_request_connection), and that statement is the liveness check: a
    pre-ping was one more round trip (~0.5 s measured) before it on every
    request. A dead connection is detected there and replaced."""
    options = _async_engine_options(url)
    if url.startswith("sqlite"):
        return options
    return {**options, "pool_size": settings.DB_REQUEST_POOL_SIZE,
            "max_overflow": settings.DB_REQUEST_MAX_OVERFLOW, "pool_pre_ping": False}


request_engine = create_async_engine(
    request_db_url, echo=False, **_request_engine_options(request_db_url)
)
RequestSessionLocal = async_sessionmaker(request_engine, expire_on_commit=False)

if settings.DB_TIMING_ENABLED:
    from app.core import db_timing
    for _engine in (engine, async_engine, request_engine):
        db_timing.attach(_engine)

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


async def _open_request_connection() -> AsyncConnection:
    """Check out the request's connection, retrying once. The Supabase pooler
    occasionally takes longer than the connect timeout for a single attempt;
    the retry a moment later usually succeeds, where the failure used to reach
    the browser as a bare 500 (reported there as a CORS error)."""
    attempts = max(1, settings.DB_CONNECT_ATTEMPTS)
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            connection = await request_engine.connect()
            if settings.DB_TIMING_ENABLED:
                from app.core import db_timing
                db_timing.record_pool_wait((time.monotonic() - started) * 1000, retries=attempt - 1)
            return connection
        except (TimeoutError, OSError, SQLAlchemyError) as exc:
            if settings.DB_TIMING_ENABLED:
                from app.core import db_timing
                db_timing.record_error(f"connect:{type(exc).__name__}")
            if attempt == attempts:
                raise
            await asyncio.sleep(0.3 * attempt)
    raise RuntimeError("unreachable")


def _is_dead_connection(exc: BaseException) -> bool:
    """The pooled connection is gone (closed by the pooler while idle, reset
    by the network), as opposed to a statement error."""
    if isinstance(exc, (ConnectionError, OSError, EOFError)):
        return True
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, (asyncpg.exceptions.ConnectionDoesNotExistError, asyncpg.exceptions.InterfaceError))


async def open_request_connection(*, tenant_id: str, user_id: str) -> AsyncConnection:
    """A request-pool connection carrying this caller's RLS identity.

    Setting the identity is the connection's first statement and doubles as
    its health check (the pool does not pre-ping). If the pooled connection
    is dead, it is invalidated, the pool's other idle connections — likely
    stale the same way — are replaced, and a fresh connection is opened."""
    for attempt in (1, 2):
        connection = await _open_request_connection()
        if settings.is_sqlite:
            return connection
        try:
            raw = await connection.get_raw_connection()
            # Set straight on the driver connection, before SQLAlchemy opens a
            # transaction on it: one round trip instead of BEGIN + SELECT +
            # COMMIT. Session-level (is_local=false), so it persists for every
            # transaction this request runs; always called, even with "", so a
            # reused connection never carries a prior request's identity.
            await raw.driver_connection.execute(
                "SELECT set_config('app.tenant_id', $1, false), set_config('app.user_id', $2, false)",
                tenant_id, user_id,
            )
            return connection
        except BaseException as exc:
            dead = _is_dead_connection(exc)
            if dead:
                await connection.invalidate()
            await connection.close()
            if not dead or attempt == 2:
                raise
            if settings.DB_TIMING_ENABLED:
                from app.core import db_timing
                db_timing.record_error(f"dead_connection:{type(exc).__name__}")
            await _refresh_request_pool()
    raise RuntimeError("unreachable")


async def _refresh_request_pool() -> None:
    """Replace the request pool's idle connections (likely stale together);
    connections already checked out stay valid for their requests."""
    await request_engine.dispose(close=False)


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
    identity = ("", "")
    if not settings.is_sqlite:
        user_id, tenant_id = _identity_from_request(request)
        identity = (tenant_id, user_id)
    # The identity is set on the connection before any transaction, and is
    # session-level, so a later rollback cannot undo it (the governed-
    # retrieval timeout handler's rollback used to erase app.tenant_id).
    connection = await open_request_connection(tenant_id=identity[0], user_id=identity[1])
    try:
        async with RequestSessionLocal(bind=connection) as session:
            # Lets rbac skip re-setting an identity that is already in place.
            session.info["rls_identity"] = identity
            yield session
    finally:
        await connection.close()
