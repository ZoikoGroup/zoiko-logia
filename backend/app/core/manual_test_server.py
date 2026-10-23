"""Isolated manual-test server: configuration guard and session limits.

Used only by scripts/run_manual_test_server.py. Nothing here runs unless that
launcher sets MANUAL_TEST_SERVER=true; production behaviour is unchanged.

A test server must not write to the shared database. Giving DATABASE_URL a
different value is not proof of that (another role on the same database, or
another port on the same Supabase project, is still the shared data), so the
guard fails closed unless:

  - a dedicated test database and a separate request role are configured,
  - neither is the shared database or in the shared Supabase project,
  - every engine the app builds can read the marker row written when the test
    database was provisioned (checked at startup, before the health sampler),
  - the request role is subject to row-level security.

Account writes are the other shared destination: with the shared project's
service-role key, signing in to a test database that has no profile for the
user stamps a new tenant onto the real account (identity/service.py
provision_profile). The test server therefore never receives that key.

Nothing in this module imports app settings at import time: the launcher must
set the test environment before get_settings() caches anything.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

MARKER_TABLE = "kriton_test_environment"
MARKER_PURPOSE = "kriton-manual-test"
MIN_MARKER_LENGTH = 16
ASK_PATHS = frozenset({"/api/v1/orchestration/ask", "/api/v1/orchestration/ask/stream"})

# answer_cache.py and websearch.py fall back to this when no URL is set.
_DEFAULT_SHARED_CACHE = "redis://localhost:6379/3"
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
_OTHER_MODEL_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                     "AZURE_OPENAI_API_KEY")
# Test-server agent settings (23 Oct 2026); each can be overridden by
# KRITON_TEST_<NAME> in the test environment file.
_TEST_AGENT_DEFAULTS = {
    "AGENT_MAX_TOKENS": "128000",
    "AGENT_MAX_COMPLETION_TOKENS": "8192",
    "AGENT_MAX_REQUEST_TOKENS": "16000",
    "AGENT_BATCH_CALCULATIONS": "true",
}
DEFAULT_MAX_QUESTIONS = 12
DEFAULT_MAX_TOTAL_TOKENS = 300_000


class ManualTestBlocked(RuntimeError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("Manual test server blocked: " + "; ".join(self.reasons))


class SessionLimitReached(RuntimeError):
    """The manual-test session's question or token allowance is used up."""


# Model calls made while handling the current question request (tasks it
# spawns inherit the context). Lets the door counter tell a request refused
# before any processing from one that did model work.
_REQUEST_MODEL_CALLS: ContextVar[list[int] | None] = ContextVar("manual_test_request_model_calls", default=None)
REFUNDED_STATUSES = frozenset({401, 403})


# ── Configuration ────────────────────────────────────────────────────────

def supabase_project(url: str) -> str | None:
    """The Supabase project a URL belongs to, or None for a non-Supabase host.
    Pooler hosts are shared by every project in a region; the project is the
    suffix of the role name (postgres.<project>)."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if host.endswith(".pooler.supabase.com"):
        user = unquote(parts.username or "")
        return user.rsplit(".", 1)[1] if "." in user else None
    if host.endswith(".supabase.co"):
        labels = host.split(".")
        return labels[1] if labels[0] == "db" and len(labels) > 3 else labels[0]
    return None


def _is_supabase(host: str) -> bool:
    return host.endswith(".supabase.com") or host.endswith(".supabase.co")


def _is_postgres(url: str) -> bool:
    return urlsplit(url).scheme.split("+")[0] in {"postgres", "postgresql"}


def database_identity(url: str) -> tuple[str, int, str, str | None]:
    """(host, port, database, Supabase project). Two URLs with the same
    identity reach the same data whatever role they log in as."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return ("localhost" if host in _LOCAL_HOSTS else host, parts.port or 5432,
            parts.path.lstrip("/") or "postgres", supabase_project(url))


def _redis_identity(url: str) -> tuple[str, int, int] | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    index = parts.path.lstrip("/") or "0"
    return ("localhost" if host in _LOCAL_HOSTS else host, parts.port or 6379, int(index) if index.isdigit() else -1)


def describe_database(url: str) -> str:
    """host:port/database as role, without the password."""
    parts = urlsplit(url)
    host, port, database, _ = database_identity(url)
    return f"{host}:{port}/{database} as {unquote(parts.username or '?')}"


def _positive_int(env: Mapping[str, str], name: str, default: int, reasons: list[str]) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    reasons.append(f"{name} must be a positive whole number")
    return default


def build_environment(test_env: Mapping[str, str | None], shared_env: Mapping[str, str | None]) -> dict[str, str]:
    """The complete environment for the test server, or ManualTestBlocked
    listing every problem. Never falls back to a shared database or cache."""
    test_env = {k: (v or "") for k, v in test_env.items()}
    shared_env = {k: v for k, v in shared_env.items() if v is not None}
    reasons: list[str] = []

    def required(name: str) -> str:
        value = test_env.get(name, "").strip()
        if not value:
            reasons.append(f"{name} is not set")
        return value

    db_url = required("KRITON_TEST_DATABASE_URL")
    app_url = required("KRITON_TEST_APP_DATABASE_URL")
    marker = required("KRITON_TEST_DATABASE_MARKER")
    redis_url = required("KRITON_TEST_REDIS_URL")
    if marker and len(marker) < MIN_MARKER_LENGTH:
        reasons.append(f"KRITON_TEST_DATABASE_MARKER must be at least {MIN_MARKER_LENGTH} characters")

    shared_databases = {name: database_identity(shared_env[name])
                        for name in ("DATABASE_URL", "APP_DATABASE_URL") if shared_env.get(name)}
    shared_projects = {project for project in [supabase_project(shared_env.get("SUPABASE_URL", "")),
                                               *(identity[3] for identity in shared_databases.values())] if project}
    postgres = {}
    for name, url in (("KRITON_TEST_DATABASE_URL", db_url), ("KRITON_TEST_APP_DATABASE_URL", app_url)):
        if not url:
            continue
        if not _is_postgres(url):
            reasons.append(f"{name} must be a PostgreSQL URL: row-level security is part of what is tested")
            continue
        try:
            identity = database_identity(url)
        except ValueError:
            reasons.append(f"{name} is not a valid URL")
            continue
        postgres[name] = identity
        if _is_supabase(identity[0]) and identity[3] is None:
            reasons.append(f"{name}: cannot tell which Supabase project this is")
        for shared_name, shared in shared_databases.items():
            if identity == shared:
                reasons.append(f"{name} is the shared database ({shared_name} in the shared .env)")
        if identity[3] and identity[3] in shared_projects:
            reasons.append(f"{name} is in the shared Supabase project ({identity[3]})")
    if len(postgres) == 2:
        if postgres["KRITON_TEST_DATABASE_URL"] != postgres["KRITON_TEST_APP_DATABASE_URL"]:
            reasons.append("KRITON_TEST_DATABASE_URL and KRITON_TEST_APP_DATABASE_URL must name the same database")
        elif urlsplit(db_url).username == urlsplit(app_url).username:
            reasons.append("KRITON_TEST_APP_DATABASE_URL must log in as a separate non-superuser role, "
                           "or row-level security is not exercised")

    if redis_url:
        shared_caches = {_redis_identity(shared_env.get(name, ""))
                         for name in ("ANSWER_CACHE_REDIS_URL", "SEARXNG_CACHE_REDIS_URL", "REDIS_URL")}
        shared_caches.add(_redis_identity(_DEFAULT_SHARED_CACHE))
        if urlsplit(redis_url).scheme not in {"redis", "rediss"}:
            reasons.append("KRITON_TEST_REDIS_URL must be a redis:// URL")
        elif _redis_identity(redis_url) in shared_caches:
            reasons.append("KRITON_TEST_REDIS_URL is a cache database the shared servers use")

    shared_auth = shared_env.get("SUPABASE_URL", "")
    test_auth = test_env.get("KRITON_TEST_SUPABASE_URL", "").strip()
    test_auth_key = test_env.get("KRITON_TEST_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if test_auth:
        project = supabase_project(test_auth)
        if project is not None and project == supabase_project(shared_auth) and test_auth_key:
            reasons.append("KRITON_TEST_SUPABASE_SERVICE_ROLE_KEY would let the test server change accounts "
                           "in the shared Supabase project")
        auth_url, auth_key = test_auth, test_auth_key
    else:
        # Sign-in tokens are verified against the shared project's public
        # keys; without the service-role key nothing is written there.
        auth_url, auth_key = shared_auth, ""
        if not shared_auth:
            reasons.append("no Supabase URL to verify sign-in tokens (set KRITON_TEST_SUPABASE_URL)")

    max_questions = _positive_int(test_env, "KRITON_TEST_MAX_QUESTIONS", DEFAULT_MAX_QUESTIONS, reasons)
    max_tokens = _positive_int(test_env, "KRITON_TEST_MAX_TOTAL_TOKENS", DEFAULT_MAX_TOTAL_TOKENS, reasons)
    if reasons:
        raise ManualTestBlocked(reasons)

    env = dict(shared_env)
    env.update({
        "MANUAL_TEST_SERVER": "true",
        "MANUAL_TEST_DATABASE_MARKER": marker,
        "MANUAL_TEST_MAX_QUESTIONS": str(max_questions),
        "MANUAL_TEST_MAX_TOTAL_TOKENS": str(max_tokens),
        "DATABASE_URL": db_url,
        "APP_DATABASE_URL": app_url,
        "SUPABASE_URL": auth_url,
        "SUPABASE_SERVICE_ROLE_KEY": auth_key,
        "REQUIRE_SUPABASE_CONFIG": "false",
        # Only seeded test profiles may sign in: an unknown account must not
        # be given a new tenant (public sign-up defaults to on).
        "ALLOW_PUBLIC_SIGNUP": "false",
        # The test database must be set up for this code (setup_database.py).
        "SKIP_STARTUP_FINGERPRINT_CHECK": "false",
        # Off unless asked for; when on it writes to the verified test database.
        "HEALTH_SAMPLER_ENABLED": "true" if test_env.get("KRITON_TEST_HEALTH_SAMPLER", "").lower() == "true"
        else "false",
        # A shared cache could serve another server's answer as this build's.
        "ANSWER_CACHE_REDIS_URL": redis_url,
        "ANSWER_CACHE_TTL_SECONDS": "0",
        "SEARXNG_CACHE_REDIS_URL": redis_url,
        "REDIS_URL": redis_url,
        "RATE_LIMIT_STORAGE_URI": "memory://",
        "CELERY_BROKER_URL": "",
        "CELERY_RESULT_BACKEND": "",
        "ASYNC_DOCUMENT_INGESTION": "false",
        "OBJECT_STORAGE_PROVIDER": "local",
        "OBJECT_STORAGE_URL": "",
        # No email from a test server; Groq is the only model provider.
        "RESEND_API_KEY": "",
        **{name: "" for name in _OTHER_MODEL_KEYS},
    })
    for name, default in _TEST_AGENT_DEFAULTS.items():
        env[name] = test_env.get(f"KRITON_TEST_{name}", "").strip() or default
    return env


# ── Startup verification (read-only) ─────────────────────────────────────

_MARKER_QUERY = f"SELECT purpose FROM {MARKER_TABLE} WHERE marker = :marker"
_ROLE_QUERY = "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"


async def verify_database(marker: str, *, admin_engine, request_engine, sync_engine) -> None:
    """Read the provisioning marker through every engine the app uses, and
    check the request role is subject to row-level security. SELECTs only."""
    from sqlalchemy import text
    import asyncio

    if len(marker or "") < MIN_MARKER_LENGTH:
        raise ManualTestBlocked(["MANUAL_TEST_DATABASE_MARKER is not set"])
    reasons: list[str] = []
    roles = {}
    for label, engine in (("setup connection", admin_engine), ("request connection", request_engine)):
        try:
            async with engine.connect() as conn:
                purpose = (await conn.execute(text(_MARKER_QUERY), {"marker": marker})).scalar()
                roles[label] = (await conn.execute(text(_ROLE_QUERY))).first()
        except Exception as exc:  # noqa: BLE001 — any failure means not verified
            reasons.append(f"{label}: no manual-test marker readable ({type(exc).__name__})")
            continue
        if purpose != MARKER_PURPOSE:
            reasons.append(f"{label}: this database is not the provisioned manual-test database")

    def _sync_purpose():
        with sync_engine.connect() as conn:
            return conn.execute(text(_MARKER_QUERY), {"marker": marker}).scalar()
    try:
        if await asyncio.to_thread(_sync_purpose) != MARKER_PURPOSE:
            reasons.append("safety-service connection: this database is not the provisioned manual-test database")
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"safety-service connection: no manual-test marker readable ({type(exc).__name__})")

    request_role = roles.get("request connection")
    if request_role is not None and (request_role[0] or request_role[1]):
        reasons.append("the request role bypasses row-level security (superuser or BYPASSRLS)")
    if reasons:
        raise ManualTestBlocked(reasons)


# ── Session limits ───────────────────────────────────────────────────────

class SessionLimits:
    """Questions and model tokens for one manual-test session, enforced in the
    server process and kept in a state file so a restart does not reset them.

    Every model call reserves an upper bound before it is sent: the request's
    UTF-8 size (a token is at least one byte) plus its completion cap. The
    total cannot be exceeded; the price is that the last question may be
    refused while some allowance is left. A failed call keeps its reservation,
    as the per-question budget does (it may still be billed)."""

    def __init__(self, max_questions: int, max_tokens: int, *, default_completion: int = 8192,
                 state_file: Path | None = None):
        self.max_questions = max_questions
        self.max_tokens = max_tokens
        self.default_completion = default_completion
        self.state_file = state_file
        self.questions = self.tokens = self.calls = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self._state_lock = None
        if state_file is not None:
            # One server per session: a second process keeping its own counts
            # in memory would double the allowance.
            self._state_lock = open(state_file.with_name(state_file.name + ".lock"), "w")
            try:
                fcntl.flock(self._state_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._state_lock.close()
                raise ManualTestBlocked([f"another manual-test server is using {state_file}"]) from None
        if state_file is not None and state_file.exists():
            try:
                saved = json.loads(state_file.read_text())
                self.questions, self.tokens, self.calls = (int(saved["questions"]), int(saved["tokens"]),
                                                           int(saved["calls"]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.close()
                raise ManualTestBlocked([f"session state file {state_file} is unreadable ({type(exc).__name__})"])

    def close(self) -> None:
        """Release the session lock (the process exiting also releases it)."""
        if self._state_lock is not None:
            self._state_lock.close()
            self._state_lock = None

    def summary(self) -> str:
        return (f"{self.questions}/{self.max_questions} questions, "
                f"{self.tokens:,}/{self.max_tokens:,} model tokens, {self.calls} model calls")

    def admit_question(self) -> str | None:
        """None when a question may start (and it is counted), else the refusal."""
        with self._lock:
            if self.questions >= self.max_questions:
                return f"Manual test limit reached: {self.questions} of {self.max_questions} questions used."
            if self.tokens + self._in_flight >= self.max_tokens:
                return f"Manual test token allowance used up: {self.tokens:,} of {self.max_tokens:,} tokens."
            self.questions += 1
            self._save()
        print(f"[manual-test] question admitted: {self.summary()}", flush=True)
        return None

    def refund_question(self) -> None:
        """Return a slot taken by a request refused before any processing."""
        with self._lock:
            if self.questions > 0:
                self.questions -= 1
                self._save()
        print(f"[manual-test] question refunded (refused before processing): {self.summary()}", flush=True)

    def reset_questions(self) -> None:
        """Supported reset: questions to 0; tokens, calls and limits kept."""
        with self._lock:
            self.questions = 0
            self._save()

    def reserve(self, kwargs: dict) -> int:
        """Reserve one model call. Adds a completion cap when the caller set
        none, so the reservation is a true upper bound."""
        from app.domains.model_gateway.agent_budget import prompt_allowance

        if not kwargs.get("max_completion_tokens") and not kwargs.get("max_tokens"):
            kwargs["max_completion_tokens"] = self.default_completion
        completion = int(kwargs.get("max_completion_tokens") or kwargs.get("max_tokens"))
        messages = [m if isinstance(m, dict) else {"content": str(m)} for m in kwargs.get("messages") or []]
        try:
            prompt = prompt_allowance(messages, kwargs.get("tools"))
        except (TypeError, ValueError):
            prompt = len(str(kwargs.get("messages")).encode("utf-8")) + len(str(kwargs.get("tools"))) + 256
        reservation = prompt + completion
        with self._lock:
            if self.tokens + self._in_flight + reservation > self.max_tokens:
                raise SessionLimitReached(
                    f"Manual test token allowance: {self.tokens:,} used, this call could need "
                    f"{reservation:,}, limit {self.max_tokens:,}")
            self._in_flight += reservation
            self.calls += 1
        request_calls = _REQUEST_MODEL_CALLS.get()
        if request_calls is not None:
            request_calls[0] += 1
        return reservation

    def settle(self, reservation: int, used: int | None) -> None:
        with self._lock:
            self._in_flight -= reservation
            self.tokens += reservation if used is None else used
            self._save()

    def _save(self) -> None:
        if self.state_file is None:
            return
        payload = json.dumps({"questions": self.questions, "tokens": self.tokens, "calls": self.calls,
                              "max_questions": self.max_questions, "max_tokens": self.max_tokens,
                              "updated_at": datetime.now(timezone.utc).isoformat()})
        handle, temporary = tempfile.mkstemp(dir=self.state_file.parent, prefix=".manual-test-")
        with os.fdopen(handle, "w") as out:
            out.write(payload)
        os.replace(temporary, self.state_file)


class QuestionLimitMiddleware:
    """Counts questions at the door and refuses them past the session limit.
    Added innermost, so CORS headers still reach the browser on a refusal.
    A request without a sign-in token is not counted (it is refused anyway).

    The slot is taken before the app runs, so concurrent requests can never
    pass the limit. It is given back only when the app answers 401 or 403
    and the request made no model call: refused by authentication or
    authorization before any question processing. A refusal after model
    work stays counted; its tokens are metered regardless."""

    def __init__(self, app, limits: SessionLimits):
        self.app = app
        self.limits = limits

    async def __call__(self, scope, receive, send):
        if not (scope["type"] == "http" and scope.get("method") == "POST" and scope.get("path") in ASK_PATHS
                and any(name == b"authorization" for name, _ in scope.get("headers", []))):
            await self.app(scope, receive, send)
            return
        refusal = self.limits.admit_question()
        if refusal is not None:
            from starlette.responses import JSONResponse
            await JSONResponse({"detail": refusal}, status_code=429)(scope, receive, send)
            return
        status: list[int] = []

        async def note_status(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)
        model_calls = [0]
        token = _REQUEST_MODEL_CALLS.set(model_calls)
        try:
            await self.app(scope, receive, note_status)
        finally:
            _REQUEST_MODEL_CALLS.reset(token)
            if status and status[0] in REFUNDED_STATUSES and model_calls[0] == 0:
                self.limits.refund_question()


def add_question_limit(app, limits: SessionLimits) -> None:
    from starlette.middleware import Middleware
    app.user_middleware.append(Middleware(QuestionLimitMiddleware, limits=limits))
