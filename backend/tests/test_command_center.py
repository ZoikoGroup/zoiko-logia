"""Command Center panels are read from Kriton's own records, scoped to the
user's tenant and to what their role may read (app/domains/command_center/service.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.command_center.service import build_command_center
from app.domains.identity.models import Engagement, EngagementGrant, EngagementMembership, Tenant, User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="Tenant One"), Tenant(id="t2", name="Tenant Two")])
        await session.commit()
        yield session
    await engine.dispose()


def _user(user_id="u1", tenant_id="t1", role="Admin") -> User:
    return User(id=user_id, tenant_id=tenant_id, email=f"{user_id}@example.com", full_name=user_id, role=role)


def _review(case_id, tenant_id="t1", status="open", risk="HIGH", at=NOW):
    return ReviewCase(id=case_id, query_id=f"q-{case_id}", correlation_id=f"c-{case_id}", tenant_id=tenant_id,
                      query_text=f"Question {case_id}", risk_level=risk, confidence_state="LOW",
                      reason="Validator rejected the draft", status=status, created_at=at)


def _escalation(case_id, tenant_id="t1", status=EscalationStatus.PENDING, sla=None, risk=RiskLevel.HIGH):
    return EscalationCase(id=case_id, tenant_id=tenant_id, query_id=f"q-{case_id}", query_text="Is this lease on balance sheet?",
                          topic="Lease classification", risk_level=risk, jurisdiction="UK", status=status,
                          sla_deadline=sla, created_at=NOW.replace(tzinfo=None))


async def test_admin_sees_every_panel_from_real_records(db):
    user = _user()
    db.add_all([
        user,
        _review("r1", at=NOW - timedelta(hours=2)), _review("r2", status="needs_evidence", at=NOW - timedelta(hours=1)),
        _escalation("e1", sla=(NOW + timedelta(days=1)).replace(tzinfo=None)),
        SecurityIncident(id="inc-1", tenant_id="t1", title="PII in an uploaded ledger", severity="Critical",
                         containment_status="OPEN", source="PII_LEAK"),
        SavedAnswer(id="sa1", tenant_id="t1", user_id="u1", query_id="q", query_text="UK VAT threshold",
                    answer_text="£90,000", risk_level="LOW", created_at=NOW - timedelta(days=1)),
        Draft(id="d1", tenant_id="t1", user_id="u1", title="Q2 compliance summary", status="Draft",
              created_at=NOW - timedelta(hours=3), updated_at=NOW - timedelta(hours=3)),
        Engagement(id="eng1", tenant_id="t1", name="Zoiko Sema Ltd · Revenue"),
        EngagementMembership(id="m1", tenant_id="t1", engagement_id="eng1", user_id="u1"),
        EngagementGrant(id="g1", tenant_id="t1", membership_id="m1", operation="*"),
    ])
    await db.commit()

    panels = await build_command_center(db, user, NOW)

    assert [c["id"] for c in panels["reviewQueue"]] == ["r2", "r1"]          # newest first
    assert panels["professionalSummary"]["reviewCount"] == 2
    kinds = [item["kind"] for item in panels["attentionItems"]]
    assert {"escalation", "incident"} <= set(kinds)
    assert all(item["level"] == "high" for item in panels["attentionItems"])
    assert [d["id"] for d in panels["deadlines"]] == ["e1"]
    assert panels["deadlines"][0]["state"] == "approaching"
    assert [w["id"] for w in panels["recentWork"]] == ["d1", "sa1"]          # merged, newest first
    assert [m["name"] for m in panels["activeMatters"]] == ["Zoiko Sema Ltd · Revenue"]
    assert all(f["state"] == "current" for f in panels["moduleFreshness"].values())


async def test_records_from_another_tenant_or_already_closed_are_left_out(db):
    user = _user()
    db.add_all([
        user,
        _review("other-tenant", tenant_id="t2"), _review("resolved", status="resolved"),
        _escalation("e-other", tenant_id="t2"), _escalation("e-done", status=EscalationStatus.RESOLVED),
        SecurityIncident(id="inc-closed", tenant_id="t1", title="Old", severity="High",
                         containment_status="RESOLVED", source="CONTROL_BYPASS"),
        SavedAnswer(id="sa-other-user", tenant_id="t1", user_id="u2", query_id="q", query_text="Not mine",
                    answer_text="a", risk_level="LOW"),
    ])
    await db.commit()

    panels = await build_command_center(db, user, NOW)

    assert panels["reviewQueue"] == [] and panels["professionalSummary"]["reviewCount"] == 0
    assert panels["attentionItems"] == [] and panels["deadlines"] == []
    assert panels["recentWork"] == []


async def test_role_without_permissions_sees_restricted_panels_not_other_data(db):
    # CFO carries no registry permissions, so review, safety, support and
    # source panels are restricted; the user's own work is still shown.
    user = _user(role="CFO")
    db.add_all([
        user, _review("r1"), _escalation("e1"),
        SavedAnswer(id="sa1", tenant_id="t1", user_id="u1", query_id="q", query_text="Mine",
                    answer_text="a", risk_level="LOW"),
    ])
    await db.commit()

    panels = await build_command_center(db, user, NOW)

    assert panels["reviewQueue"] == [] and panels["attentionItems"] == [] and panels["deadlines"] == []
    for panel in ("reviewQueue", "attentionItems", "deadlines"):
        assert panels["moduleFreshness"][panel]["state"] == "restricted"
    assert [w["id"] for w in panels["recentWork"]] == ["sa1"]


async def test_an_empty_workspace_reports_empty_current_panels(db):
    user = _user()
    db.add(user)
    await db.commit()

    panels = await build_command_center(db, user, NOW)

    for key in ("attentionItems", "activeMatters", "deadlines", "reviewQueue", "recentWork"):
        assert panels[key] == []
    assert panels["professionalSummary"]["attentionCount"] == 0


async def test_overdue_escalation_deadline_is_marked_overdue(db):
    user = _user()
    db.add_all([user, _escalation("late", sla=(NOW - timedelta(hours=5)).replace(tzinfo=None))])
    await db.commit()

    panels = await build_command_center(db, user, NOW)

    assert panels["deadlines"][0]["state"] == "overdue"
