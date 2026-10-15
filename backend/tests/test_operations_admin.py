"""Operations and Administration pages read real configuration and records.

They used to show invented providers, alerts, service health, invoices and
client companies. Pins that every value now comes from the running config or
the tenant's own rows, that secret values never leave the backend, that tenants
stay isolated, and that the pages are role-gated.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.admin_governance import overview
from app.domains.operations.router import require_operations
from app.domains.identity.models import ServiceAccount, Tenant, User
from app.domains.kriton_workspace.models import SavedAnswer
from app.domains.operations import service as operations
from app.orchestration.models import QueryAnswerRecord

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
SECRET = "sk-test-SECRET-value-123"


def _user(uid, tenant, role, active=True):
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", first_name=uid, last_name="",
                full_name=uid, role=role, is_active=active)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme Ltd"), Tenant(id="t2", name="Other Co"),
            _user("admin", "t1", "Admin"), _user("rev", "t1", "SME Reviewer"),
            _user("old", "t1", "CFO"), _user("gone", "t1", "Source Admin", active=False),
            _user("svc", "t1", "System Auditor"), _user("b-admin", "t2", "Admin"),
            ServiceAccount(id="svc", tenant_id="t1", name="ERP sync", owner_user_id="admin", created_by="admin"),
            QueryAnswerRecord(query_id="q1", tenant_id="t1", user_id="admin", question="a", created_at=NOW - timedelta(days=1)),
            QueryAnswerRecord(query_id="q2", tenant_id="t1", user_id="rev", question="b", created_at=NOW - timedelta(days=2)),
            QueryAnswerRecord(query_id="q3", tenant_id="t1", user_id="admin", question="c", created_at=NOW - timedelta(days=40)),
            QueryAnswerRecord(query_id="q4", tenant_id="t2", user_id="b-admin", question="d", created_at=NOW - timedelta(days=1)),
            SavedAnswer(id="s1", tenant_id="t1", user_id="admin", query_id="q1", query_text="a", answer_text="x",
                        risk_level="LOW"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


# ── Operations ──────────────────────────────────────────────────────────────

def test_connections_report_presence_never_secret_values(monkeypatch) -> None:
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "FRED_API_KEY", "SEARXNG_URL",
                "GROQ_FAST_ANSWER_MODEL", "GROQ_CLASSIFIER_MODEL", "GROQ_VERIFIER_MODEL"):
        monkeypatch.delenv(var, raising=False)  # the developer's own .env must not leak into the test
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.setenv("GROQ_MODEL", "llama-test")
    monkeypatch.setenv("FRED_API_KEY", "<fred-api-key>")  # .env.example placeholder ≠ configured
    monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "groq")

    providers = {p["key"]: p for p in operations.model_providers()}
    assert providers["groq"]["configured"] is True and providers["groq"]["approved"] is True
    assert providers["groq"]["models"] == {"GROQ_MODEL": "llama-test"}
    assert providers["openai"]["configured"] is False and providers["openai"]["approved"] is False
    assert all(p["dueDiligence"] == "not_assessed" for p in providers.values())
    fred = next(s for s in operations.data_sources() if s["name"].startswith("FRED"))
    assert fred["configured"] is False
    searx = next(i for i in operations.integrations() if i["name"] == "SearXNG")
    assert searx["configured"] is False

    payload = json.dumps([operations.model_providers(), operations.data_sources(), operations.integrations()])
    assert SECRET not in payload


async def test_dependency_checks_are_live_and_honest(db, monkeypatch) -> None:
    class _Settings:
        SUPABASE_URL = ""
        SUPABASE_SERVICE_ROLE_KEY = ""
    monkeypatch.setattr(operations, "get_settings", lambda: _Settings())
    for var in ("SEARXNG_URL", "KROKI_URL", "CELERY_BROKER_URL", "REDIS_URL", "GROQ_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    checks = {c["key"]: c for c in await operations.dependency_checks(db)}
    assert checks["database"]["state"] == "operational" and checks["database"]["latencyMs"] is not None
    assert checks["supabase_auth"]["state"] == "not_configured"
    assert checks["searxng"]["state"] == "not_configured"
    assert checks["groq"]["state"] == "not_configured", "no key: never probed, never reported up"
    audit = await operations.audit_chain_check(db, "t1")
    assert audit["state"] == "operational"


async def test_operations_pages_are_role_gated(db) -> None:
    assert await require_operations(await db.get(User, "admin")) is not None
    with pytest.raises(HTTPException) as exc:
        await require_operations(await db.get(User, "rev"))
    assert exc.value.status_code == 403


# ── Administration ─────────────────────────────────────────────────────────

async def test_roles_matrix_is_the_real_registry(db) -> None:
    matrix = await overview.roles_matrix(db, "t1")
    roles = {r["name"]: r for r in matrix["roles"]}
    assert {"Admin", "SME Reviewer", "Learner"} <= set(roles), "roles missing from the old table are listed"
    assert roles["SME Reviewer"]["permissions"] == ["review.read", "review.resolve"]
    assert roles["Admin"]["activeUsers"] == 1
    assert roles["Source Admin"]["activeUsers"] == 0, "inactive users are not counted"
    assert roles["System Auditor"]["activeUsers"] == 0, "service accounts are not people"
    assert matrix["unrecognisedRoles"] == [{"name": "CFO", "activeUsers": 1}]


async def test_tenant_settings_are_real(db) -> None:
    settings = await overview.tenant_settings(db, "t1")
    assert settings["workspace"]["name"] == "Acme Ltd"
    assert settings["people"] == {"total": 4, "active": 3, "inactive": 1, "serviceAccounts": 1,
                                  "byRole": {"Admin": 1, "SME Reviewer": 1, "CFO": 1}}
    labels = {s["label"] for s in settings["security"]}
    assert "MFA required for privileged actions" in labels and "Public sign-up" in labels
    assert all(s["source"].startswith("Deployment setting") for s in settings["security"] + settings["retention"])


async def test_usage_is_measured_per_tenant_and_billing_not_faked(db) -> None:
    result = await overview.usage(db, "t1", now=NOW)
    totals = result["totals"]
    assert totals["questions_all_time"] == 3
    assert totals["questions_this_month"] == 2
    assert totals["active_users_this_month"] == 2
    assert totals["saved_answers"] == 1
    months = {m["month"]: m["questions"] for m in result["questionsByMonth"]}
    assert months["2026-10"] == 2 and months["2026-09"] == 1
    assert len(result["questionsByMonth"]) == 6
    assert result["billing"]["connected"] is False

    other = await overview.usage(db, "t2", now=NOW)
    assert other["totals"]["questions_all_time"] == 1


def test_placeholder_secrets_are_not_used_as_headers():
    from app.domains.operations.service import _usable_secret

    assert _usable_secret("eyJhbGciOiJIUzI1NiJ9.e30.sig") is True
    for bad in ("", None, "<service-role-key>", "your-service-role…", "your_key_here", "changeme"):
        assert _usable_secret(bad) is False
