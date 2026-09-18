"""
The per-request identity that Postgres RLS depends on must survive a commit.

app.tenant_id and app.user_id live on a CONNECTION, not on a session. A session
normally returns its connection to the pool at every commit and checks one out
again for the next statement — and a request that commits part-way, as every
audit write does, can then be handed a connection that never had set_config run
on it. Every RLS-protected statement after that point sees nothing.

The failure hides on a quiet pool, because the connection just released is
usually the one handed straight back. It appeared in a real upload: the row was
inserted and committed, and the very next UPDATE on that same row matched zero
rows. The row was real and the policy was right; the new connection simply had
no identity on it.

The first test below asserts the STRUCTURAL guarantee — get_db binds one
connection — because that is deterministic. A race-based test was tried first
and rejected: it passed with the fix reverted, since a quiet pool hands the same
connection straight back, and a test that cannot fail is worse than no test.
The second test demonstrates the failure mechanism itself by forcing another
request to take the connection in between.
"""
import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import RequestSessionLocal, get_db, request_engine

settings = get_settings()

IDENTITY = "identity-under-test"
PROBE = "SELECT pg_backend_pid(), current_setting('app.user_id', true)"


class _RequestWithoutToken:
    """get_db only reads headers; an unauthenticated request still has to set
    both settings, so this is enough to exercise the binding."""
    headers: dict[str, str] = {}


async def test_get_db_binds_the_session_to_a_single_connection():
    """The guarantee, asserted structurally so it cannot silently stop holding.

    A session bound to an Engine acquires and releases a connection per
    transaction; one bound to a Connection keeps that connection for its
    lifetime. Only the second makes a session-scoped `set_config` meaningful.
    """
    agen = get_db(_RequestWithoutToken())          # type: ignore[arg-type]
    session = await agen.__anext__()
    try:
        bind = session.get_bind()
        assert type(bind).__name__ == "Connection", (
            f"get_db bound the session to {type(bind).__name__}; the RLS identity "
            "set at the start of the request will not exist on whatever "
            "connection the pool hands over after the first commit"
        )
    finally:
        await agen.aclose()


async def test_a_session_bound_to_a_connection_keeps_its_identity_across_a_commit():
    """The mechanism, demonstrated end to end against live Postgres."""
    if settings.is_sqlite:
        print("SKIPPED (SQLite has no RLS and no session settings)")
        return

    grabbed, release = asyncio.Event(), asyncio.Event()

    async def take_the_connection() -> None:
        """A concurrent request claiming the connection ours just released."""
        async with RequestSessionLocal() as other:
            await other.execute(
                text("SELECT set_config('app.user_id', 'a-different-request', false)")
            )
            await other.execute(text("SELECT 1"))
            grabbed.set()
            await release.wait()
            await other.commit()

    async with request_engine.connect() as connection, \
            RequestSessionLocal(bind=connection) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :u, false)"), {"u": IDENTITY}
        )
        before = (await session.execute(text(PROBE))).first()
        await session.commit()

        thief = asyncio.create_task(take_the_connection())
        await grabbed.wait()
        after = (await session.execute(text(PROBE))).first()
        release.set()
        await thief

    assert after[1] == IDENTITY, (
        f"identity lost after commit: {before[1]!r} on pid {before[0]} became "
        f"{after[1]!r} on pid {after[0]}"
    )
    assert before[0] == after[0], "the request moved to a different connection"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and asyncio.iscoroutinefunction(fn):
            asyncio.run(fn())
            print(f"  {name}: PASS")
