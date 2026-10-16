"""Super Admin Command Center: platform metadata across tenants.

Pins: only a person holding users.platform_role reaches it (a tenant Admin,
an API key or an impersonated session is refused, and every refusal is
audited); the overview counts across tenants but never carries customer
content (incident titles, break-glass reasons, dispute reasons).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.billing.models import BillingAdjustment
from app.domains.identity.models import BreakGlassGrant, Tenant, User
from app.domains.platform import service
from app.domains.platform.router import require_super_admin
from app.domains.support_incident.models import SecurityIncident

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Globex"),
                         User(id="a1", tenant_id="t1", email="a1@x.com", full_name="Ann", role="Admin"),
                         User(id="b1", tenant_id="t2", email="b1@x.com", full_name="Bob", role="Learner"),
                         User(id="p1", tenant_id="t1", email="p1@x.com", full_name="Pat", role="Learner",
                              platform_role="super_admin")])
        await session.commit()
        yield session
    await engine.dispose()


async def test_only_platform_role_is_admitted_and_refusals_are_audited(db) -> None:
    admin = await db.get(User, "a1")
    with pytest.raises(HTTPException) as refused:
        await require_super_admin(admin, db)
    assert refused.value.status_code == 403, "a tenant Admin is not a Super Admin"

    platform = await db.get(User, "p1")
    assert await require_super_admin(platform, db) is platform, "the platform role works whatever the tenant role"

    platform.impersonated_by = "a1"
    with pytest.raises(HTTPException):
        await require_super_admin(platform, db)
    platform.impersonated_by = None
    platform.auth_method = "api_key"
    with pytest.raises(HTTPException):
        await require_super_admin(platform, db)
    platform.auth_method = "session"

    denied = (await db.execute(select(AuditEvent).where(AuditEvent.event_name == "access_denied"))).scalars().all()
    assert sorted(e.payload["reason"] for e in denied) == ["impersonation", "missing_platform_role", "service_account"]
    assert all(e.payload["required"] == "platform.super_admin" for e in denied)


async def test_overview_counts_across_tenants_without_customer_content(db) -> None:
    db.add_all([
        SecurityIncident(tenant_id="t1", title="Payroll ledger of Acme leaked", severity="Critical", source="PII_LEAK"),
        SecurityIncident(tenant_id="t2", title="Globex minor", severity="High", source="CONTROL_BYPASS",
                         assigned_to="b1"),
        BreakGlassGrant(tenant_id="t2", user_id="b1", permissions=["audit.correct"], reason="Fix client Zeta invoices",
                        duration_minutes=60, status="requested"),
        BreakGlassGrant(tenant_id="t1", user_id="a1", permissions=["safety.manage"], reason="Hotfix",
                        duration_minutes=30, status="expired", ended_at=NOW - timedelta(hours=1)),
        BillingAdjustment(tenant_id="t1", period="2026-10", kind="dispute", meter="model_input",
                          reason="Duplicate events for client Zeta", status="open", created_by="a1"),
    ])
    await db.commit()

    view = await service.command_overview(db, now=NOW)
    summary = view["summary"]
    assert summary["criticalIncidents"] == 1 and summary["openIncidents"] == 2 and summary["unassignedIncidents"] == 1
    assert summary["privilegedAwaitingApproval"] == 1 and summary["privilegedRequests"] == 2
    assert view["commercial"]["openDisputes"] == 1
    assert view["tenants"]["total"] == 2 and view["tenants"]["users"] == 3

    queue = view["decisions"]
    assert [d["priority"] for d in queue][:2] == ["Critical", "Critical"], "critical items lead the queue"
    assert {d["tenant"] for d in queue} == {"Acme", "Globex"}

    dumped = json.dumps(view)
    for secret in ("Payroll ledger", "Zeta", "Hotfix", "audit.correct", "Duplicate events"):
        assert secret not in dumped, f"customer content leaked: {secret}"


async def test_empty_platform_reports_unknown_not_zero_health(db) -> None:
    view = await service.command_overview(db, now=NOW)
    assert view["health"]["sampled"] is False and view["summary"]["availabilityPct"] is None
    controls = {c["key"]: c["state"] for c in view["controls"]}
    assert controls["resilience"] == "unknown" and controls["evaluation"] == "unknown"
    assert view["decisions"] == []
