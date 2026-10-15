"""Billing & Usage: usage measured from the audit ledger, priced with the
approved plan version for each month.

Pins: meters count and sum the right events per tenant; with no approved
plan nothing is priced; a plan, a credit and a dispute decision each need a
different Admin; a disputed meter is excluded from the estimate; each month
uses the plan version in effect then; a closed month is a statement and
cannot be closed or adjusted again.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.billing import service
from app.domains.identity.models import Engagement, Tenant, User

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Other"),
                         User(id="a1", tenant_id="t1", email="a1@x.com", full_name="Ann", role="Admin"),
                         User(id="a2", tenant_id="t1", email="a2@x.com", full_name="Bob", role="Admin"),
                         Engagement(id="e1", tenant_id="t1", name="FY26 audit")])
        await session.commit()
        yield session
    await engine.dispose()


async def _event(db, tenant, name, payload=None):
    await record_event_async(db, tenant_id=tenant, event_name=name, emitting_service="test", actor_id="a1",
                             subject_type="query", subject_id="q", payload=payload or {})


async def _usage(db):
    for _ in range(3):
        await _event(db, "t1", "query_received")
    await _event(db, "t1", "model_run_completed", {"input_length": 2_000_000})
    await _event(db, "t1", "kriton_workspace.attachment_uploaded", {"size_bytes": 500_000_000})
    await _event(db, "t1", "task_context_resolved", {"effective_context": {"engagement_id": "e1"}})
    await _event(db, "t1", "task_context_resolved", {"effective_context": {}})
    await _event(db, "t2", "query_received")


async def _approved_plan(db, **overrides):
    a1, a2 = await db.get(User, "a1"), await db.get(User, "a2")
    plan = await service.propose_plan(db, a1, {
        "name": "ZoikoLogia Enterprise", "commitment_cents": 1_200_000, "effective_from": "2026-01",
        "included": {"kriton_interactions": 1}, "rates": {"kriton_interactions": 1000, "model_input": 500, "document_uploads": 200},
        "soft_budget_cents": 1_800_000, **overrides})
    return await service.decide_plan(db, a2, plan.id, True, "")


async def test_usage_is_measured_per_tenant_and_unpriced_without_a_plan(db) -> None:
    await _usage(db)
    start, end = service.bounds("2026-10")
    usage = await service.measure(db, "t1", datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))
    assert usage["totals"]["kriton_interactions"] == 3
    assert usage["totals"]["model_input"] == 2.0 and usage["totals"]["document_uploads"] == 0.5
    assert usage["engagements"] == {"e1": 1, None: 1}
    priced = service.price(None, usage["totals"], [])
    assert not priced["priced"] and priced["totalCents"] == 0


async def test_plan_and_adjustments_need_a_second_admin(db) -> None:
    a1, a2 = await db.get(User, "a1"), await db.get(User, "a2")
    plan = await service.propose_plan(db, a1, {"name": "Pro", "effective_from": "2026-10"})
    with pytest.raises(service.BillingError, match="different Admin"):
        await service.decide_plan(db, a1, plan.id, True, "")
    await service.decide_plan(db, a2, plan.id, True, "")
    credit = await service.add_adjustment(db, a1, kind="credit", period="2026-10", reason="SLA miss", amount_cents=30_000)
    with pytest.raises(service.BillingError, match="different Admin"):
        await service.decide_adjustment(db, a1, credit.id, "approved", "")
    await service.decide_adjustment(db, a2, credit.id, "approved", "")


async def test_charges_use_the_plan_and_exclude_disputed_meters(db) -> None:
    await _usage(db)
    plan = await _approved_plan(db)
    usage = {"kriton_interactions": 3, "model_input": 2.0, "tool_calls": 0, "external_data_calls": 0, "document_uploads": 0.5}
    priced = service.price(plan, usage, [])
    lines = {l["key"]: l for l in priced["lines"]}
    assert lines["commitment"]["amountCents"] == 1_200_000
    assert lines["kriton_interactions"]["billable"] == 2 and lines["kriton_interactions"]["amountCents"] == 2000
    assert lines["model_input"]["amountCents"] == 1000 and lines["document_uploads"]["amountCents"] == 100
    assert priced["totalCents"] == 1_203_100

    a1 = await db.get(User, "a1")
    dispute = await service.add_adjustment(db, a1, kind="dispute", period="2026-10", reason="Duplicate events", meter="model_input")
    priced = service.price(plan, usage, [dispute])
    assert priced["excludedCents"] == 1000 and priced["totalCents"] == 1_202_100


async def test_month_uses_its_own_plan_version_and_closes_once(db) -> None:
    a1, a2 = await db.get(User, "a1"), await db.get(User, "a2")
    v1 = await _approved_plan(db)
    v2 = await service.propose_plan(db, a1, {"name": "Enterprise 2", "commitment_cents": 1_500_000, "effective_from": "2026-11"})
    await service.decide_plan(db, a2, v2.id, True, "")
    plans = await service._plans(db, "t1")
    assert service.plan_for(plans, "2026-10").version == v1.version
    assert service.plan_for(plans, "2026-11").version == v2.version
    assert service.plan_for(plans, "2025-12") is None

    with pytest.raises(service.BillingError, match="finished month"):
        await service.close_period(db, a1, "2026-10", now=NOW)
    statement = await service.close_period(db, a1, "2026-09", now=NOW)
    assert statement.ref == "INV-2026-001" and statement.total_cents == 1_200_000
    with pytest.raises(service.BillingError, match="already closed"):
        await service.close_period(db, a1, "2026-09", now=NOW)
    with pytest.raises(service.BillingError, match="closed"):
        await service.add_adjustment(db, a1, kind="credit", period="2026-09", reason="late credit", amount_cents=100)
    paid = await service.mark_paid(db, a2, statement.id, "Wire 4471")
    assert paid.status == "paid"


async def test_overview_shapes_trend_allocation_and_budget(db) -> None:
    await _usage(db)
    await _approved_plan(db)
    view = await service.overview(db, "t1", now=datetime.now(timezone.utc))
    assert len(view["trend"]) == 6 and view["summary"]["priced"]
    assert {a["name"] for a in view["allocation"]} == {"FY26 audit", "Unassigned (no engagement)"}
    assert view["summary"]["budgetUsedPct"] is not None
    assert (await service.overview(db, "t2", now=datetime.now(timezone.utc)))["plan"] is None, "tenants stay isolated"
