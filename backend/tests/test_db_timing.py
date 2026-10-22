"""db_timing: per-request database timings, and that they leak nothing.

Off by default; when on, a request's pool wait, new connections, pre-pings,
statement kinds and durations are summarised in one log line. Only a
statement's kind and table are kept, never its text or parameters."""
import json
import logging

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import db_timing
from app.core.config import get_settings


def test_timing_is_off_by_default():
    assert get_settings().DB_TIMING_ENABLED is False


def test_a_statement_is_recorded_by_kind_and_table_only():
    assert db_timing.category('SELECT * FROM "users" WHERE email = $1') == "SELECT users"
    assert db_timing.category("INSERT INTO audit_events (id) VALUES (:id)") == "INSERT audit_events"
    assert db_timing.category("UPDATE query_answer_records SET x=1") == "UPDATE query_answer_records"
    assert db_timing.category("SELECT set_config('app.tenant_id', $1, false)") == "SELECT -"


def test_a_request_summary_counts_queries_repeats_and_connections(caplog):
    engine = create_engine("sqlite://", pool_pre_ping=True)
    db_timing.attach(engine)
    with db_timing.request_scope("req-1", "/api/x") as stats:
        with engine.connect() as connection:
            for _ in range(3):
                connection.execute(text("SELECT 1"))
            connection.execute(text("SELECT :secret_value"), {"secret_value": "card 4111-1111"})
        with caplog.at_level(logging.INFO, logger="kriton.db_timing"):
            summary = db_timing.log_summary(stats, 200)
    assert summary["sql_count"] == 4 and summary["new_connections"] == 1
    assert list(summary["repeated"].values()) == [3]                 # the same statement three times
    logged = caplog.records[-1].getMessage()
    assert "4111" not in logged and "secret_value" not in logged and "SELECT 1" not in logged
    assert json.loads(logged.split(" ", 1)[1])["request_id"] == "req-1"


def test_nothing_is_recorded_outside_a_request():
    engine = create_engine("sqlite://")
    db_timing.attach(engine)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))                       # no scope: no error, nothing kept
    assert db_timing.current() is None


async def test_async_engines_are_timed_too():
    engine = create_async_engine("sqlite+aiosqlite://")
    db_timing.attach(engine)
    with db_timing.request_scope("req-2", "/api/y") as stats:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    assert len(stats.queries) == 1 and stats.queries[0][0] == "SELECT -"
    await engine.dispose()


async def test_the_middleware_adds_server_timing_and_logs_one_line(caplog):
    sent = []

    async def app(scope, receive, send):
        db_timing.record_pool_wait(12.5, retries=1)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        sent.append(message)
    with caplog.at_level(logging.INFO, logger="kriton.db_timing"):
        await db_timing.DbTimingMiddleware(app)(
            {"type": "http", "path": "/api/kriton/ask", "headers": [(b"idempotency-key", b"idem-1")]},
            None, send)
    assert (b"server-timing", b"sql;dur=0, pool;dur=12") in sent[0]["headers"]
    summary = json.loads(caplog.records[-1].getMessage().split(" ", 1)[1])
    assert summary["request_id"] == "idem-1" and summary["retries"] == 1 and summary["status"] == 200


@pytest.mark.parametrize("path", ["/api/kriton/ask"])
async def test_a_websocket_or_lifespan_scope_passes_through(path):
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])
    await db_timing.DbTimingMiddleware(app)({"type": "lifespan"}, None, None)
    assert called == ["lifespan"]


# ── Request pool: kept connections, identity as the health check ────────────

from types import SimpleNamespace as N

from app.core import database


def test_the_request_pool_keeps_its_connections_and_does_not_pre_ping():
    options = database._request_engine_options("postgresql+asyncpg://u:p@h:5432/d")
    assert options["pool_size"] == 6 and options["max_overflow"] == 0 and options["pool_pre_ping"] is False
    # The other pools are unchanged.
    other = database._async_engine_options("postgresql+asyncpg://u:p@h:5432/d")
    assert other["pool_pre_ping"] is True and other["pool_size"] == 3


class _FakeConnection:
    def __init__(self, fail_with=None):
        self.fail_with, self.executed, self.invalidated, self.closed = fail_with, [], False, False

    async def get_raw_connection(self):
        async def execute(sql, *args):
            if self.fail_with:
                raise self.fail_with
            self.executed.append(args)
        return N(driver_connection=N(execute=execute))

    async def invalidate(self):
        self.invalidated = True

    async def close(self):
        self.closed = True


def _postgres(monkeypatch, connections):
    monkeypatch.setattr(database.settings, "DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    queue = list(connections)

    async def open_one():
        return queue.pop(0)
    monkeypatch.setattr(database, "_open_request_connection", open_one)
    disposed = []

    async def refresh():
        disposed.append(False)
    monkeypatch.setattr(database, "_refresh_request_pool", refresh)
    return disposed


async def test_every_connection_gets_the_callers_identity_even_an_empty_one(monkeypatch):
    first, second = _FakeConnection(), _FakeConnection()
    _postgres(monkeypatch, [first, second])
    assert await database.open_request_connection(tenant_id="t1", user_id="u1") is first
    assert await database.open_request_connection(tenant_id="", user_id="") is second
    assert first.executed == [("t1", "u1")] and second.executed == [("", "")]


async def test_a_dead_pooled_connection_is_replaced_and_the_pool_refreshed(monkeypatch):
    dead, fresh = _FakeConnection(ConnectionResetError("reset by peer")), _FakeConnection()
    disposed = _postgres(monkeypatch, [dead, fresh])
    assert await database.open_request_connection(tenant_id="t1", user_id="u1") is fresh
    assert dead.invalidated and dead.closed and disposed == [False]   # checked-out connections are kept
    assert fresh.executed == [("t1", "u1")]


async def test_a_statement_error_is_not_retried(monkeypatch):
    broken = _FakeConnection(ValueError("not a connection problem"))
    _postgres(monkeypatch, [broken, _FakeConnection()])
    with pytest.raises(ValueError):
        await database.open_request_connection(tenant_id="t1", user_id="u1")
    assert broken.closed and not broken.invalidated


async def test_two_dead_connections_in_a_row_fail_rather_than_loop(monkeypatch):
    _postgres(monkeypatch, [_FakeConnection(ConnectionResetError()), _FakeConnection(BrokenPipeError())])
    with pytest.raises(BrokenPipeError):
        await database.open_request_connection(tenant_id="t1", user_id="u1")
