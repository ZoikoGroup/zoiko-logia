"""Per-request database timings, for diagnosing latency (off by default).

Enabled by DB_TIMING_ENABLED. Records, per HTTP request: time waiting for a
pooled connection, time establishing new connections, pre-ping health checks,
each SQL statement's duration, retries and errors — and logs one summary line
when the request ends. Only a statement's kind and main table are recorded
(e.g. "SELECT users"), with a hash to spot repeats: never SQL text, bound
parameters, credentials, tokens, prompts or financial data.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import event

logger = logging.getLogger("kriton.db_timing")

_KIND = re.compile(r"^\s*(select|insert|update|delete|with|begin|commit|rollback|set|show|savepoint|release)\b", re.I)
_TABLE = re.compile(r"\b(?:from|into|update|join)\s+\"?([a-z_][a-z0-9_]*)\"?", re.I)


@dataclass
class RequestDbStats:
    request_id: str
    path: str
    started: float = field(default_factory=time.monotonic)
    queries: list[tuple[str, str, float]] = field(default_factory=list)   # (category, hash, ms)
    pool_wait_ms: float = 0.0
    checkouts: int = 0
    connects: list[float] = field(default_factory=list)                   # ms per new connection
    pings: list[float] = field(default_factory=list)                      # ms per pre-ping
    retries: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self, status: int | None = None) -> dict:
        db_ms = sum(ms for _, _, ms in self.queries)
        repeated: dict[str, int] = {}
        for category, digest, _ in self.queries:
            repeated[f"{category}#{digest}"] = repeated.get(f"{category}#{digest}", 0) + 1
        by_category: dict[str, list[float]] = {}
        for category, _, ms in self.queries:
            by_category.setdefault(category, []).append(ms)
        return {
            "request_id": self.request_id, "path": self.path, "status": status,
            "http_ms": round((time.monotonic() - self.started) * 1000, 1),
            "sql_count": len(self.queries), "sql_ms": round(db_ms, 1),
            "pool_wait_ms": round(self.pool_wait_ms, 1), "checkouts": self.checkouts,
            "new_connections": len(self.connects), "connect_ms": [round(ms, 1) for ms in self.connects],
            "pings": len(self.pings), "ping_ms": round(sum(self.pings), 1),
            "retries": self.retries, "errors": self.errors,
            "slowest": sorted(({"category": c, "ms": round(ms, 1)} for c, _, ms in self.queries),
                              key=lambda item: -item["ms"])[:5],
            "repeated": {key: count for key, count in repeated.items() if count > 1},
            "by_category": {key: {"count": len(values), "ms": round(sum(values), 1)}
                            for key, values in sorted(by_category.items(), key=lambda kv: -sum(kv[1]))},
        }


_current: ContextVar[RequestDbStats | None] = ContextVar("db_timing_current", default=None)


def current() -> RequestDbStats | None:
    return _current.get()


@contextmanager
def request_scope(request_id: str, path: str):
    stats = RequestDbStats(request_id=request_id, path=path)
    token = _current.set(stats)
    try:
        yield stats
    finally:
        _current.reset(token)


def category(statement: str) -> str:
    kind = _KIND.match(statement or "")
    table = _TABLE.search(statement or "")
    return f"{(kind.group(1) if kind else 'other').upper()} {table.group(1) if table else '-'}"


def record_pool_wait(ms: float, retries: int = 0) -> None:
    stats = current()
    if stats is not None:
        stats.pool_wait_ms += ms
        stats.checkouts += 1
        stats.retries += retries


def record_error(kind: str) -> None:
    stats = current()
    if stats is not None:
        stats.errors.append(kind)


def attach(engine) -> None:
    """Register the timing listeners on a (sync or async) engine, once."""
    sync_engine = getattr(engine, "sync_engine", engine)
    if getattr(sync_engine, "_kriton_db_timing", False):
        return
    sync_engine._kriton_db_timing = True

    @event.listens_for(sync_engine, "do_connect")
    def _connect_start(dialect, conn_rec, cargs, cparams):
        conn_rec.info["kriton_connect_started"] = time.monotonic()

    @event.listens_for(sync_engine, "connect")
    def _connected(dbapi_connection, conn_rec):
        started = conn_rec.info.pop("kriton_connect_started", None)
        stats = current()
        if stats is not None and started is not None:
            stats.connects.append((time.monotonic() - started) * 1000)

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("kriton_query_started", []).append(time.monotonic())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        started = conn.info.get("kriton_query_started") or [time.monotonic()]
        begun = started.pop()
        stats = current()
        if stats is not None:
            digest = hashlib.sha256((statement or "").encode()).hexdigest()[:10]
            stats.queries.append((category(statement), digest, (time.monotonic() - begun) * 1000))

    @event.listens_for(sync_engine, "handle_error")
    def _error(context):
        stack = context.connection.info.get("kriton_query_started") if context.connection is not None else None
        if stack:
            stack.pop()
        record_error(type(context.original_exception).__name__)

    dialect = sync_engine.dialect
    original_ping = dialect.do_ping

    def timed_ping(dbapi_connection):
        begun = time.monotonic()
        try:
            return original_ping(dbapi_connection)
        finally:
            stats = current()
            if stats is not None:
                stats.pings.append((time.monotonic() - begun) * 1000)
    dialect.do_ping = timed_ping


def log_summary(stats: RequestDbStats, status: int | None) -> dict:
    summary = stats.summary(status)
    logger.info("db_timing %s", json.dumps(summary, default=str))
    return summary


class DbTimingMiddleware:
    """Pure ASGI middleware: one timing scope per HTTP request, closed only
    after the whole response (a streamed body included) has been sent. Adds a
    Server-Timing header (sql;dur, pool;dur) when the headers are sent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers") or []}
        request_id = (headers.get("x-request-id") or headers.get("idempotency-key")
                      or f"req-{time.time_ns():x}")[:80]
        status: dict = {}
        with request_scope(request_id, scope.get("path", "")) as stats:
            async def timed_send(message):
                if message.get("type") == "http.response.start":
                    status["code"] = message.get("status")
                    timing = (f"sql;dur={sum(ms for _, _, ms in stats.queries):.0f}, "
                              f"pool;dur={stats.pool_wait_ms:.0f}").encode()
                    message = {**message, "headers": [*message.get("headers", []), (b"server-timing", timing)]}
                await send(message)
            try:
                await self.app(scope, receive, timed_send)
            finally:
                log_summary(stats, status.get("code"))
