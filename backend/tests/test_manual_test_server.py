"""Isolated manual-test server (23 Oct 2026). No database, model or network.

The test server used the developer's .env, so its chats, audit records, usage
and health samples went to the shared Supabase database, and signing in to an
unprovisioned database would have stamped a new tenant onto the real account.
These tests pin the guard: missing, unverified or shared configuration fails
closed, and the session limits are enforced in code.
"""
import json
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core import manual_test_server as mts
from app.core.manual_test_server import (
    ManualTestBlocked, SessionLimitReached, SessionLimits, build_environment, database_identity,
    supabase_project,
)

SHARED_REF = "sharedproject0001"
SHARED = {
    "DATABASE_URL": f"postgresql://postgres.{SHARED_REF}:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres",
    "APP_DATABASE_URL": f"postgresql://zoiko_app.{SHARED_REF}:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres",
    "SUPABASE_URL": f"https://{SHARED_REF}.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "shared-service-role-key",
    "SEARXNG_CACHE_REDIS_URL": "redis://localhost:6379/3",
    "RESEND_API_KEY": "shared-email-key",
    "GROQ_API_KEY": "groq-key",
    "GOOGLE_API_KEY": "google-key",
    "SKIP_STARTUP_FINGERPRINT_CHECK": "true",
    "KRITON_AGENT_MODE": "true",
    "EMPTY_IN_FILE": None,
}
MARKER = "m4rker-0123456789abcdef"
VALID = {
    "KRITON_TEST_DATABASE_URL": "postgresql://kriton_test_owner:pw@127.0.0.1:5432/kriton_manual_test",
    "KRITON_TEST_APP_DATABASE_URL": "postgresql://kriton_test_app:pw@localhost:5432/kriton_manual_test",
    "KRITON_TEST_DATABASE_MARKER": MARKER,
    "KRITON_TEST_REDIS_URL": "redis://localhost:6379/9",
}


def _blocked(test_env, shared=SHARED) -> list[str]:
    with pytest.raises(ManualTestBlocked) as raised:
        build_environment(test_env, shared)
    return raised.value.reasons


# ── Configuration fails closed ───────────────────────────────────────────

def test_no_test_configuration_is_refused_with_every_missing_setting():
    reasons = _blocked({})
    for name in ("KRITON_TEST_DATABASE_URL", "KRITON_TEST_APP_DATABASE_URL", "KRITON_TEST_DATABASE_MARKER",
                 "KRITON_TEST_REDIS_URL"):
        assert f"{name} is not set" in reasons


@pytest.mark.parametrize("missing", list(VALID))
def test_each_required_setting_is_required(missing):
    assert f"{missing} is not set" in _blocked({**VALID, missing: ""})


def test_the_shared_database_itself_is_refused():
    reasons = _blocked({**VALID, "KRITON_TEST_DATABASE_URL": SHARED["DATABASE_URL"],
                        "KRITON_TEST_APP_DATABASE_URL": SHARED["APP_DATABASE_URL"]})
    assert any("is the shared database" in r for r in reasons)
    assert any("shared Supabase project" in r for r in reasons)


def test_another_port_or_role_on_the_shared_project_is_still_shared():
    # The transaction pooler (6543) and another role reach the same data.
    url = f"postgresql://someone.{SHARED_REF}:pw@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
    reasons = _blocked({**VALID, "KRITON_TEST_DATABASE_URL": url, "KRITON_TEST_APP_DATABASE_URL": url})
    assert any("shared Supabase project" in r for r in reasons)


def test_a_different_role_on_the_same_database_is_not_isolation():
    shared = {**SHARED, "DATABASE_URL": "postgresql://owner:pw@127.0.0.1:5432/kriton",
              "APP_DATABASE_URL": "", "SUPABASE_URL": "https://other.supabase.co"}
    reasons = _blocked({**VALID, "KRITON_TEST_DATABASE_URL": "postgresql://tester:pw@localhost/kriton",
                        "KRITON_TEST_APP_DATABASE_URL": "postgresql://tester_app:pw@localhost/kriton"}, shared)
    assert any("is the shared database (DATABASE_URL" in r for r in reasons)


def test_a_supabase_url_whose_project_cannot_be_told_is_refused():
    url = "postgresql://postgres:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    reasons = _blocked({**VALID, "KRITON_TEST_DATABASE_URL": url})
    assert any("cannot tell which Supabase project" in r for r in reasons)


def test_a_separate_supabase_project_is_accepted():
    url = "postgresql://postgres.testproject9:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    app = "postgresql://kriton_test_app.testproject9:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    env = build_environment({**VALID, "KRITON_TEST_DATABASE_URL": url, "KRITON_TEST_APP_DATABASE_URL": app}, SHARED)
    assert env["DATABASE_URL"] == url and env["APP_DATABASE_URL"] == app


@pytest.mark.parametrize("url", ["sqlite+aiosqlite:///./manual.db", "mysql://u:p@localhost/x"])
def test_a_database_without_row_level_security_is_refused(url):
    assert any("must be a PostgreSQL URL" in r for r in _blocked({**VALID, "KRITON_TEST_DATABASE_URL": url}))


def test_the_request_role_must_differ_from_the_setup_role_on_the_same_database():
    same_role = {**VALID, "KRITON_TEST_APP_DATABASE_URL": VALID["KRITON_TEST_DATABASE_URL"]}
    assert any("separate non-superuser role" in r for r in _blocked(same_role))
    other_db = {**VALID, "KRITON_TEST_APP_DATABASE_URL": "postgresql://kriton_test_app:pw@localhost/elsewhere"}
    assert any("must name the same database" in r for r in _blocked(other_db))


@pytest.mark.parametrize("redis_url", ["redis://localhost:6379/3", "redis://127.0.0.1:6379/3"])
def test_the_shared_cache_is_refused(redis_url):
    assert any("cache database the shared servers use" in r
               for r in _blocked({**VALID, "KRITON_TEST_REDIS_URL": redis_url}))


def test_the_default_shared_cache_is_refused_even_when_the_shared_env_names_none():
    shared = {k: v for k, v in SHARED.items() if k != "SEARXNG_CACHE_REDIS_URL"}
    assert any("cache database" in r for r in _blocked({**VALID, "KRITON_TEST_REDIS_URL": "redis://localhost/3"},
                                                       shared))


def test_a_short_marker_is_refused():
    assert any("at least 16" in r for r in _blocked({**VALID, "KRITON_TEST_DATABASE_MARKER": "short"}))


def test_a_service_role_key_for_the_shared_auth_project_is_refused():
    reasons = _blocked({**VALID, "KRITON_TEST_SUPABASE_URL": SHARED["SUPABASE_URL"],
                        "KRITON_TEST_SUPABASE_SERVICE_ROLE_KEY": "key"})
    assert any("change accounts in the shared Supabase project" in r for r in reasons)


@pytest.mark.parametrize("name, value", [("KRITON_TEST_MAX_QUESTIONS", "0"), ("KRITON_TEST_MAX_TOTAL_TOKENS", "lots")])
def test_limits_must_be_positive_numbers(name, value):
    assert any(name in r for r in _blocked({**VALID, name: value}))


# ── The environment a valid configuration produces ───────────────────────

def test_no_shared_database_cache_or_account_key_reaches_the_test_server():
    env = build_environment(VALID, SHARED)
    shared_secrets = {SHARED["DATABASE_URL"], SHARED["APP_DATABASE_URL"], SHARED["SUPABASE_SERVICE_ROLE_KEY"],
                      SHARED["SEARXNG_CACHE_REDIS_URL"], SHARED["RESEND_API_KEY"]}
    assert not shared_secrets & set(env.values())
    assert env["DATABASE_URL"] == VALID["KRITON_TEST_DATABASE_URL"]
    assert env["APP_DATABASE_URL"] == VALID["KRITON_TEST_APP_DATABASE_URL"]
    assert env["SUPABASE_URL"] == SHARED["SUPABASE_URL"] and env["SUPABASE_SERVICE_ROLE_KEY"] == ""
    for cache in ("ANSWER_CACHE_REDIS_URL", "SEARXNG_CACHE_REDIS_URL", "REDIS_URL"):
        assert env[cache] == VALID["KRITON_TEST_REDIS_URL"]
    assert env["ANSWER_CACHE_TTL_SECONDS"] == "0"
    assert env["CELERY_BROKER_URL"] == "" and env["OBJECT_STORAGE_PROVIDER"] == "local"


def test_the_test_server_verifies_its_database_and_checks_the_setup_fingerprint():
    env = build_environment(VALID, SHARED)
    assert env["MANUAL_TEST_SERVER"] == "true" and env["MANUAL_TEST_DATABASE_MARKER"] == MARKER
    assert env["SKIP_STARTUP_FINGERPRINT_CHECK"] == "false"


def test_the_health_sampler_is_off_unless_asked_for():
    assert build_environment(VALID, SHARED)["HEALTH_SAMPLER_ENABLED"] == "false"
    assert build_environment({**VALID, "KRITON_TEST_HEALTH_SAMPLER": "true"}, SHARED)["HEALTH_SAMPLER_ENABLED"] == "true"


def test_only_seeded_profiles_may_sign_in():
    assert build_environment(VALID, SHARED)["ALLOW_PUBLIC_SIGNUP"] == "false"


async def test_without_the_service_key_signing_in_cannot_change_the_real_account(monkeypatch):
    import httpx
    from app.core import supabase_admin
    from app.core.config import get_settings
    from app.domains.identity import service

    def no_network(*args, **kwargs):
        raise AssertionError("the Supabase admin API was called")
    for verb in ("get", "post", "put", "delete", "request"):
        monkeypatch.setattr(httpx, verb, no_network)
    monkeypatch.setattr(get_settings(), "SUPABASE_URL", "https://sharedproject0001.supabase.co")
    monkeypatch.setattr(get_settings(), "SUPABASE_SERVICE_ROLE_KEY", "")
    assert not supabase_admin.is_configured()
    with pytest.raises(supabase_admin.SupabaseNotConfiguredError):
        supabase_admin.update_app_metadata("user-1", "test-tenant", "Admin")
    # A seeded profile whose tenant differs from the token's real tenant: the
    # repair is skipped and sign-in proceeds with the test profile.
    seeded = SimpleNamespace(id="user-1", tenant_id="test-tenant", role="Admin")
    user = await service.provision_profile(None, "user-1", "me@example.com", SimpleNamespace(),
                                           token_tenant_id="real-tenant", token_role="Admin", existing=seeded)
    assert user is seeded


async def test_an_unseeded_account_is_refused_not_given_a_tenant(monkeypatch):
    from fastapi import HTTPException
    from app.core.config import get_settings
    from app.domains.identity import service

    monkeypatch.setattr(get_settings(), "ALLOW_PUBLIC_SIGNUP", False)
    with pytest.raises(HTTPException) as refused:
        await service.provision_profile(None, "stranger", "x@example.com", SimpleNamespace(), existing=None)
    assert refused.value.status_code == 403


def test_groq_is_the_only_model_provider_and_no_email_is_sent():
    env = build_environment(VALID, SHARED)
    assert env["GROQ_API_KEY"] == "groq-key"
    assert env["GOOGLE_API_KEY"] == env["OPENAI_API_KEY"] == env["RESEND_API_KEY"] == ""


def test_test_only_agent_settings_and_limits():
    env = build_environment(VALID, SHARED)
    assert (env["AGENT_MAX_TOKENS"], env["AGENT_MAX_COMPLETION_TOKENS"], env["AGENT_MAX_REQUEST_TOKENS"],
            env["AGENT_BATCH_CALCULATIONS"]) == ("128000", "8192", "16000", "true")
    assert (env["MANUAL_TEST_MAX_QUESTIONS"], env["MANUAL_TEST_MAX_TOTAL_TOKENS"]) == ("12", "300000")
    assert build_environment({**VALID, "KRITON_TEST_AGENT_MAX_TOKENS": "64000"}, SHARED)["AGENT_MAX_TOKENS"] == "64000"


def test_production_defaults_are_unchanged():
    from app.core.config import Settings
    fields = Settings.model_fields
    assert fields["MANUAL_TEST_SERVER"].default is False and fields["MANUAL_TEST_DATABASE_MARKER"].default == ""
    assert fields["AGENT_BATCH_CALCULATIONS"].default is False and fields["HEALTH_SAMPLER_ENABLED"].default is True


@pytest.mark.parametrize("url, project", [
    (f"postgresql://postgres.{SHARED_REF}:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres", SHARED_REF),
    ("postgresql://postgres:pw@db.abc123.supabase.co:5432/postgres", "abc123"),
    ("https://abc123.supabase.co", "abc123"),
    ("postgresql://u:p@localhost/x", None),
])
def test_supabase_project_is_read_from_the_url(url, project):
    assert supabase_project(url) == project


def test_localhost_spellings_are_one_host():
    assert database_identity("postgresql://a@127.0.0.1/db") == database_identity("postgresql://b@localhost:5432/db")


# ── Startup verification reads the marker through every engine ───────────

class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def first(self):
        return self.value


class _Conn:
    def __init__(self, purpose, role, fail):
        self.purpose, self.role, self.fail = purpose, role, fail
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if self.fail:
            raise RuntimeError("relation \"kriton_test_environment\" does not exist")
        return _Result(self.purpose if mts.MARKER_TABLE in sql else self.role)


class _AsyncConn(_Conn):
    async def execute(self, statement, params=None):
        return _Conn.execute(self, statement, params)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SyncConn(_Conn):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Engine:
    def __init__(self, purpose=mts.MARKER_PURPOSE, role=(False, False), fail=False, sync=False):
        self.conn = (_SyncConn if sync else _AsyncConn)(purpose, role, fail)

    def connect(self):
        return self.conn


def _engines(**overrides):
    engines = {"admin_engine": _Engine(), "request_engine": _Engine(), "sync_engine": _Engine(sync=True)}
    engines.update(overrides)
    return engines


async def test_a_provisioned_test_database_passes_with_selects_only():
    engines = _engines()
    await mts.verify_database(MARKER, **engines)
    statements = [s for e in engines.values() for s in e.conn.statements]
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)


async def test_the_shared_database_has_no_marker_and_is_refused():
    with pytest.raises(ManualTestBlocked) as raised:
        await mts.verify_database(MARKER, **_engines(admin_engine=_Engine(fail=True)))
    assert any("setup connection" in r for r in raised.value.reasons)


@pytest.mark.parametrize("engine", ["admin_engine", "request_engine", "sync_engine"])
async def test_any_engine_reaching_another_database_is_refused(engine):
    other = _Engine(purpose=None, sync=engine == "sync_engine")
    with pytest.raises(ManualTestBlocked):
        await mts.verify_database(MARKER, **_engines(**{engine: other}))


@pytest.mark.parametrize("role", [(True, False), (False, True)])
async def test_a_request_role_that_bypasses_rls_is_refused(role):
    with pytest.raises(ManualTestBlocked) as raised:
        await mts.verify_database(MARKER, **_engines(request_engine=_Engine(role=role)))
    assert any("row-level security" in r for r in raised.value.reasons)


async def test_no_marker_configured_is_refused_before_connecting():
    engines = _engines()
    with pytest.raises(ManualTestBlocked):
        await mts.verify_database("", **engines)
    assert not any(e.conn.statements for e in engines.values())


async def test_startup_stops_before_the_health_sampler_when_verification_fails(monkeypatch):
    from app import main
    from app.domains.operations import telemetry

    started = []
    monkeypatch.setattr(main.settings, "MANUAL_TEST_SERVER", True)
    monkeypatch.setattr(main.settings, "HEALTH_SAMPLER_ENABLED", True)

    async def refuse(*args, **kwargs):
        raise ManualTestBlocked(["no marker"])

    async def fingerprint():
        started.append("fingerprint")

    async def sampler(*args):
        started.append("sampler")
    monkeypatch.setattr(mts, "verify_database", refuse)
    monkeypatch.setattr(main, "_stored_fingerprint", fingerprint)
    monkeypatch.setattr(telemetry, "run_sampler", sampler)
    with pytest.raises(ManualTestBlocked):
        async with main.lifespan(main.app):
            pass
    assert started == []


async def test_a_normal_server_does_not_run_the_check(monkeypatch):
    from app import main

    async def must_not_run(*args, **kwargs):
        raise AssertionError("verification ran on a normal server")

    async def stop(*args):
        raise RuntimeError("stop after the check point")
    monkeypatch.setattr(main.settings, "MANUAL_TEST_SERVER", False)
    monkeypatch.setattr(mts, "verify_database", must_not_run)
    monkeypatch.setattr(main, "_stored_fingerprint", stop)
    with pytest.raises(RuntimeError, match="stop after"):
        async with main.lifespan(main.app):
            pass


# ── Session limits are enforced, not described ───────────────────────────

def test_questions_past_the_limit_are_refused():
    limits = SessionLimits(2, 100_000)
    assert limits.admit_question() is None and limits.admit_question() is None
    assert "2 of 2 questions" in limits.admit_question()
    assert limits.questions == 2


def test_a_call_that_could_pass_the_token_limit_is_refused_before_it_is_sent():
    # 9,000 completion + ~850 request bytes cannot fit in 9,500.
    limits = SessionLimits(12, 9_500)
    call = {"model": "m", "messages": [{"role": "user", "content": "x" * 500}], "max_completion_tokens": 9_000}
    with pytest.raises(SessionLimitReached):
        limits.reserve(call)
    assert limits.calls == 0 and limits.tokens == 0


def test_actual_usage_is_counted_and_a_failed_call_keeps_its_reservation():
    limits = SessionLimits(12, 100_000)
    first = limits.reserve({"messages": [{"role": "user", "content": "hi"}], "max_completion_tokens": 1_000})
    limits.settle(first, 700)
    second = limits.reserve({"messages": [{"role": "user", "content": "hi"}], "max_completion_tokens": 1_000})
    limits.settle(second, None)
    assert limits.tokens == 700 + second and limits.calls == 2


def test_a_call_without_a_completion_cap_gets_one_so_the_reservation_bounds_it():
    limits = SessionLimits(12, 100_000, default_completion=8192)
    call = {"messages": [{"role": "user", "content": "hi"}]}
    reservation = limits.reserve(call)
    assert call["max_completion_tokens"] == 8192 and reservation > 8192


def test_no_new_question_once_the_tokens_are_used_up():
    limits = SessionLimits(12, 1_000)
    limits.settle(limits.reserve({"messages": [], "max_completion_tokens": 600}), 1_000)
    assert "token allowance used up" in limits.admit_question()


def test_the_counts_survive_a_restart(tmp_path):
    state = tmp_path / "session.json"
    limits = SessionLimits(3, 50_000, state_file=state)
    limits.admit_question()
    limits.settle(limits.reserve({"messages": [], "max_completion_tokens": 100}), 4_321)
    limits.close()   # the process exiting
    again = SessionLimits(3, 50_000, state_file=state)
    assert (again.questions, again.tokens, again.calls) == (1, 4_321, 1)
    again.close()


def test_a_second_server_cannot_share_the_session(tmp_path):
    state = tmp_path / "session.json"
    first = SessionLimits(3, 50_000, state_file=state)
    with pytest.raises(ManualTestBlocked, match="another manual-test server"):
        SessionLimits(3, 50_000, state_file=state)
    first.close()
    SessionLimits(3, 50_000, state_file=state).close()


def test_concurrent_questions_cannot_pass_the_limit():
    from concurrent.futures import ThreadPoolExecutor
    limits = SessionLimits(12, 1_000_000)
    with ThreadPoolExecutor(max_workers=25) as pool:
        results = list(pool.map(lambda _: limits.admit_question(), range(60)))
    assert results.count(None) == 12 and limits.questions == 12


def test_concurrent_model_calls_cannot_pass_the_token_limit():
    from concurrent.futures import ThreadPoolExecutor
    limits = SessionLimits(12, 100_000)
    call = {"messages": [{"role": "user", "content": "q"}], "max_completion_tokens": 9_000}

    def one(_):
        try:
            reservation = limits.reserve(dict(call))
        except SessionLimitReached:
            return 0
        limits.settle(reservation, None)   # worst case: the whole reservation is used
        return reservation
    with ThreadPoolExecutor(max_workers=25) as pool:
        spent = sum(pool.map(one, range(60)))
    assert spent == limits.tokens <= 100_000 and limits.calls == 10


def test_an_unreadable_state_file_blocks_the_server(tmp_path):
    state = tmp_path / "session.json"
    state.write_text("{not json")
    with pytest.raises(ManualTestBlocked):
        SessionLimits(3, 50_000, state_file=state)


async def test_every_groq_completion_is_metered_and_refused_past_the_limit(monkeypatch):
    from groq.resources.chat import completions as module

    sent = []

    async def fake_create(self, **kwargs):
        sent.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=1_234))

    def fake_sync_create(self, **kwargs):
        sent.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=1_000))
    monkeypatch.setattr(module.AsyncCompletions, "create", fake_create)
    monkeypatch.setattr(module.Completions, "create", fake_sync_create)
    from app.domains.model_gateway.session_meter import install_groq_meter
    limits = SessionLimits(12, 12_000)
    uninstall = install_groq_meter(limits)
    try:
        call = {"model": "m", "messages": [{"role": "user", "content": "q"}], "max_completion_tokens": 4_000}
        await module.AsyncCompletions.create(None, **call)
        module.Completions.create(None, **call)
        assert limits.tokens == 2_234 and len(sent) == 2
        with pytest.raises(SessionLimitReached):
            await module.AsyncCompletions.create(None, **{**call, "max_completion_tokens": 9_900})
        assert len(sent) == 2   # refused before the transport
    finally:
        uninstall()
    assert module.AsyncCompletions.create is fake_create


def _app(limits):
    async def ask(request):
        return JSONResponse({"ok": True})
    app = Starlette(routes=[Route(path, ask, methods=["POST"]) for path in mts.ASK_PATHS]
                    + [Route("/api/v1/orchestration/feedback", ask, methods=["POST"])],
                    middleware=[Middleware(CORSMiddleware, allow_origins=["http://localhost:3001"],
                                           allow_methods=["*"], allow_headers=["*"])])
    mts.add_question_limit(app, limits)
    return TestClient(app)


def test_the_server_refuses_questions_past_the_limit_with_cors_headers():
    limits = SessionLimits(2, 100_000)
    client = _app(limits)
    headers = {"Authorization": "Bearer t", "Origin": "http://localhost:3001"}
    assert client.post("/api/v1/orchestration/ask", headers=headers).status_code == 200
    assert client.post("/api/v1/orchestration/ask/stream", headers=headers).status_code == 200
    refused = client.post("/api/v1/orchestration/ask", headers=headers)
    assert refused.status_code == 429 and "2 of 2 questions" in refused.json()["detail"]
    assert refused.headers["access-control-allow-origin"] == "http://localhost:3001"


def test_only_signed_in_questions_are_counted():
    limits = SessionLimits(1, 100_000)
    client = _app(limits)
    client.post("/api/v1/orchestration/feedback", headers={"Authorization": "Bearer t"})
    client.post("/api/v1/orchestration/ask")
    client.options("/api/v1/orchestration/ask", headers={"Origin": "http://localhost:3001",
                                                         "Access-Control-Request-Method": "POST"})
    assert limits.questions == 0


# ── Refused before processing: the question slot is given back ───────────

def _status_app(limits, status, model_calls=0):
    """An app that answers `status`, after `model_calls` metered model calls."""
    async def ask(request):
        for _ in range(model_calls):
            limits.settle(limits.reserve({"messages": [{"role": "user", "content": "q"}],
                                          "max_completion_tokens": 100}), 50)
        return JSONResponse({"detail": "x"}, status_code=status)
    app = Starlette(routes=[Route(path, ask, methods=["POST"]) for path in mts.ASK_PATHS])
    mts.add_question_limit(app, limits)
    return TestClient(app)


SIGNED = {"Authorization": "Bearer t"}


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("path", sorted(mts.ASK_PATHS))
def test_a_request_refused_before_processing_does_not_use_a_slot(status, path):
    limits = SessionLimits(12, 100_000)
    assert _status_app(limits, status).post(path, headers=SIGNED).status_code == status
    assert limits.questions == 0


def test_a_valid_question_still_uses_a_slot():
    limits = SessionLimits(12, 100_000)
    client = _status_app(limits, 200, model_calls=1)
    assert client.post("/api/v1/orchestration/ask", headers=SIGNED).status_code == 200
    assert (limits.questions, limits.calls, limits.tokens) == (1, 1, 50)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_refusal_after_model_work_stays_counted(status):
    limits = SessionLimits(12, 100_000)
    _status_app(limits, status, model_calls=1).post("/api/v1/orchestration/ask", headers=SIGNED)
    assert limits.questions == 1 and limits.tokens == 50


@pytest.mark.parametrize("status", [400, 404, 422, 429, 500])
def test_other_failures_before_processing_stay_counted(status):
    limits = SessionLimits(12, 100_000)
    _status_app(limits, status).post("/api/v1/orchestration/ask", headers=SIGNED)
    assert limits.questions == 1


def test_the_real_app_refuses_a_forged_token_without_using_a_slot():
    """The real ask endpoint and its real authentication: a forged token is
    401 and the slot comes back. The database dependency is replaced so no
    connection is opened."""
    from app.core.database import get_db
    from app.main import app

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    try:
        limits = SessionLimits(12, 100_000)
        client = TestClient(mts.QuestionLimitMiddleware(app, limits))
        response = client.post("/api/v1/orchestration/ask", json={"query": "smoke"},
                               headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401 and limits.questions == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_the_limit_still_holds_with_refunds_mixed_in():
    limits = SessionLimits(2, 100_000)
    ok, refused = _status_app(limits, 200, model_calls=1), _status_app(limits, 401)
    assert refused.post("/api/v1/orchestration/ask", headers=SIGNED).status_code == 401
    assert ok.post("/api/v1/orchestration/ask", headers=SIGNED).status_code == 200
    assert refused.post("/api/v1/orchestration/ask", headers=SIGNED).status_code == 401
    assert ok.post("/api/v1/orchestration/ask", headers=SIGNED).status_code == 200
    third = ok.post("/api/v1/orchestration/ask", headers=SIGNED)
    assert third.status_code == 429 and "2 of 2 questions" in third.json()["detail"]
    assert limits.questions == 2


async def test_concurrent_refusals_and_questions_never_pass_the_limit():
    """40 concurrent requests, half refused at sign-in: exactly the limit's
    worth of real questions is admitted, and refusals never free a slot a
    concurrent real question then exceeds the limit with."""
    import asyncio
    import httpx
    limits = SessionLimits(5, 1_000_000)

    async def ask(request):
        await asyncio.sleep(0.01)
        if request.headers.get("x-kind") == "refused":
            return JSONResponse({"detail": "no"}, status_code=401)
        limits.settle(limits.reserve({"messages": [], "max_completion_tokens": 10}), 10)
        return JSONResponse({"ok": True})
    app = Starlette(routes=[Route("/api/v1/orchestration/ask", ask, methods=["POST"])])
    mts.add_question_limit(app, limits)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        kinds = ["refused", "real"] * 20
        responses = await asyncio.gather(*(client.post("/api/v1/orchestration/ask",
                                                       headers={**SIGNED, "x-kind": k}) for k in kinds))
    codes = [r.status_code for r in responses]
    assert codes.count(200) <= 5 and limits.questions == codes.count(200)
    assert limits.calls == codes.count(200) and limits.tokens == 10 * codes.count(200)


def test_the_reset_sets_questions_to_zero_and_keeps_tokens_and_limits(tmp_path):
    state = tmp_path / "session.json"
    limits = SessionLimits(12, 300_000, state_file=state)
    limits.admit_question()
    limits.settle(limits.reserve({"messages": [], "max_completion_tokens": 100}), 777)
    limits.reset_questions()
    limits.close()
    again = SessionLimits(12, 300_000, state_file=state)
    assert (again.questions, again.tokens, again.calls, again.max_tokens) == (0, 777, 1, 300_000)
    again.close()


def test_the_launcher_reset_is_refused_while_a_server_holds_the_session(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "launcher_reset", Path(__file__).resolve().parents[1] / "scripts" / "run_manual_test_server.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    test_env, shared_env = tmp_path / ".env.manual-test", tmp_path / "shared.env"
    test_env.write_text("".join(f"{k}={v}\n" for k, v in VALID.items()))
    shared_env.write_text("".join(f"{k}={v}\n" for k, v in SHARED.items() if v))
    state = tmp_path / "s.json"
    monkeypatch.setattr(launcher, "_verify_marker", lambda: (_ for _ in ()).throw(AssertionError("no DB")))
    import os
    before = dict(os.environ)
    running = SessionLimits(12, 300_000, state_file=state)       # a server holding the session
    running.admit_question()
    args = ["--test-env", str(test_env), "--shared-env", str(shared_env), "--state-file", str(state),
            "--reset-questions"]
    assert launcher.main(args) == 2 and "another manual-test server" in capsys.readouterr().out
    running.close()
    assert launcher.main(args) == 0 and "1/12 questions" in capsys.readouterr().out
    assert json.loads(state.read_text())["questions"] == 0
    assert dict(os.environ) == before            # reset loads no application code


def test_the_counted_paths_are_the_real_question_endpoints():
    from app.main import app
    paths = app.openapi()["paths"]   # included routers are nested in this FastAPI
    assert all("post" in paths.get(path, {}) for path in mts.ASK_PATHS)


# ── A sign-in token's production tenant never scopes test-database work ───

async def test_every_profile_request_is_rescoped_to_the_profile_tenant(monkeypatch):
    """The token carries the production tenant; the seeded test profile has
    the test tenant. get_current_user must move the session to the profile's
    tenant, keeping the token's user id, before anything else runs."""
    from app.domains.identity import rbac

    executed = []

    class Session:
        info = {"rls_identity": ("production-tenant", "user-1")}   # what get_db set from the token

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))

        async def commit(self):
            executed.append(("COMMIT", None))
    profile = SimpleNamespace(id="user-1", tenant_id="test-tenant", is_active=True, role="Admin")
    monkeypatch.setattr(rbac, "verify_token", lambda token: SimpleNamespace(
        sub="user-1", tenant_id="production-tenant", role="Admin", aal="aal1", email="x@example.com"))
    monkeypatch.setattr(rbac, "session_is_sqlite", lambda db: False)

    async def by_id(db, user_id):
        return profile if user_id == "user-1" else None

    async def no_break_glass(db, user):
        return set()
    monkeypatch.setattr(rbac, "get_user_by_id", by_id)
    monkeypatch.setattr(rbac.governance, "active_break_glass_permissions", no_break_glass)
    session = Session()
    user = await rbac.get_current_user(token="token", db=session, impersonation_session=None)
    assert user.tenant_id == "test-tenant"
    assert ("SELECT set_config('app.tenant_id', :tenant_id, false)", {"tenant_id": "test-tenant"}) in executed
    assert session.info["rls_identity"] == ("test-tenant", "user-1")
    assert all("production-tenant" not in str(params) for _, params in executed)


def test_only_sign_in_provisioning_opens_a_token_scoped_session_without_the_profile():
    """Every other route that opens get_db also resolves the profile, which
    re-scopes the tenant. /auth/provision reads the user's own row (matched by
    user id, not tenant) and, with public sign-up off and no service key,
    writes nothing for a seeded profile."""
    from fastapi.routing import APIRoute
    from app.core import database
    from app.main import app

    def walk(routes, prefix=""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
            elif type(route).__name__ == "_IncludedRouter":
                yield from walk(route.original_router.routes,
                                prefix + (getattr(route.include_context, "prefix", "") or ""))

    def calls(dependant):
        for dep in dependant.dependencies:
            yield dep.call
            yield from calls(dep)

    profile = ("get_current_user", "require_permission", "require_role", "require_platform", "require_admin")
    unscoped = sorted({path for path, route in walk(app.routes)
                       if database.get_db in list(calls(route.dependant))
                       and not any(k in getattr(c, "__qualname__", "") for c in calls(route.dependant) for k in profile)})
    assert len(unscoped) == 1 and unscoped[0].endswith("/auth/provision"), unscoped


# ── The launcher refuses before loading the application ──────────────────

def test_the_launcher_refuses_an_incomplete_configuration(tmp_path, monkeypatch, capsys):
    import importlib.util
    import os
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_manual_test_server", Path(__file__).resolve().parents[1] / "scripts" / "run_manual_test_server.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    test_env, shared_env = tmp_path / ".env.manual-test", tmp_path / "shared.env"
    test_env.write_text(f"KRITON_TEST_DATABASE_URL={SHARED['DATABASE_URL']}\n")
    shared_env.write_text("\n".join(f"{k}={v}" for k, v in SHARED.items() if v) + "\n")
    before = dict(os.environ)

    def must_not_run(*args, **kwargs):
        raise AssertionError("the server or database check ran")
    monkeypatch.setattr(launcher, "_verify_marker", must_not_run)
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", must_not_run)
    assert launcher.main(["--test-env", str(test_env), "--shared-env", str(shared_env)]) == 2
    out = capsys.readouterr().out
    assert "NOT started" in out and "shared Supabase project" in out
    assert dict(os.environ) == before
    assert json.dumps(before).count(SHARED_REF) == json.dumps(dict(os.environ)).count(SHARED_REF)
