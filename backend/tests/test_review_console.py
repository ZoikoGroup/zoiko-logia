"""Review, Escalation & Audit console.

Pins that one question is decided once (its review case closes its
escalation, and the escalation cannot be decided separately), the
escalation rules (experts only, maker-checker, independent critical sign-off),
the support SLA clock (at risk, breached, paused while waiting), ticket
hand-offs into escalations and incidents, incident rules, audit event
classification, and that an audit export needs a different Admin and never
contains payloads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import Tenant, User
from app.domains.review_console import audit, escalations, incidents, tickets
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel
from app.domains.support_incident.models import SupportTicket
from app.orchestration.models import ReviewCase

NOW = datetime.now(timezone.utc)


def _user(uid, tenant, role):
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", full_name=uid.title(), role=role, is_active=True)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Other"),
                         _user("admin", "t1", "Admin"), _user("admin2", "t1", "Admin"), _user("risk", "t1", "Risk Admin"),
                         _user("sme", "t1", "SME Reviewer"), _user("learner", "t1", "Learner"), _user("b", "t2", "Admin")])
        await session.commit()
        yield session
    await engine.dispose()


async def _u(db, uid):
    return await db.get(User, uid)


def _escalation(cid, query_id, risk="HIGH", owner="learner"):
    return EscalationCase(id=cid, tenant_id="t1", query_id=query_id, query_text="Is this lease IFRS 16?", topic="Lease",
                          risk_level=RiskLevel(risk), jurisdiction="UK", owner=owner, status=EscalationStatus.PENDING,
                          sla_deadline=(NOW - timedelta(hours=1)).replace(tzinfo=None), created_at=NOW.replace(tzinfo=None))


async def test_one_question_is_decided_once(db) -> None:
    db.add_all([_escalation("ESC-1", "q1"),
                ReviewCase(id="rc1", query_id="q1", correlation_id="q1", tenant_id="t1", query_text="Is this lease IFRS 16?",
                           risk_level="HIGH", confidence_state="LOW", reason="escalation", draft_answer="Yes")])
    await db.commit()
    risk = await _u(db, "risk")
    view = await escalations.queue(db, "t1")
    esc = view["escalations"][0]
    assert esc["reviewCase"]["id"] == "rc1" and esc["closureRestricted"] and esc["sla"] == "overdue"
    with pytest.raises(escalations.EscalationError, match="Review Tasks"):
        await escalations.act(db, risk, "ESC-1", "approve")

    review = await db.get(ReviewCase, "rc1")
    review.status, review.reviewer_decision, review.reviewer_id = "resolved", "corrected", "sme"
    await db.commit()
    assert await escalations.sync_from_review(db, review) == 1
    case = await db.get(EscalationCase, "ESC-1")
    assert case.status == EscalationStatus.RESOLVED and case.reviewer_decision == "review:corrected"
    assert (await escalations.queue(db, "t2"))["escalations"] == [], "tenants stay isolated"


async def test_escalation_rules(db) -> None:
    db.add(_escalation("ESC-2", "q2", risk="RESTRICTED"))
    await db.commit()
    risk, sme, learner = await _u(db, "risk"), await _u(db, "sme"), await _u(db, "learner")
    with pytest.raises(escalations.EscalationError, match="cannot decide"):
        await escalations.act(db, risk, "ESC-2", "assign", assignee_id="learner")
    await escalations.act(db, risk, "ESC-2", "assign", assignee_id="sme")
    with pytest.raises(escalations.EscalationError, match="independent"):
        await escalations.act(db, sme, "ESC-2", "approve")
    with pytest.raises(escalations.EscalationError, match="someone else"):
        await escalations.act(db, learner, "ESC-2", "approve")
    with pytest.raises(escalations.EscalationError, match="reason"):
        await escalations.act(db, risk, "ESC-2", "refuse")
    case = await escalations.act(db, risk, "ESC-2", "approve", note="Treatment confirmed")
    assert case.status == EscalationStatus.RESOLVED
    assert [h["action"] for h in case.history] == ["assign", "approve"]


async def test_ticket_sla_clock_and_handoffs(db) -> None:
    admin, risk = await _u(db, "admin"), await _u(db, "risk")
    t = await tickets.create(db, admin, subject="SSO sign-in loop", description="Two users loop at sign-in",
                             category="access_identity", priority_="P1")
    t.created_at = NOW - timedelta(hours=7)
    assert tickets.sla(t, NOW)["state"] == "at_risk", "7h into an 8h P1 target"
    assert tickets.sla(t, NOW)["firstResponseMet"] is False, "no response within the 1h first-response target"
    t.created_at = NOW - timedelta(hours=9)
    assert tickets.sla(t, NOW)["state"] == "breached"

    t.created_at = NOW - timedelta(hours=2)
    await tickets.act(db, admin, t.id, "status", new_status="waiting_customer")
    t.waiting_since = NOW - timedelta(hours=1)
    assert tickets.sla(t, NOW)["state"] == "paused"
    await tickets.act(db, admin, t.id, "customer_update", body="Screenshots attached")
    assert t.paused_seconds >= 3600 and t.status == "in_progress"

    await tickets.act(db, admin, t.id, "escalate", body="Needs a security decision")
    assert t.status == "escalated" and t.escalation_id
    esc = await db.get(EscalationCase, t.escalation_id)
    assert esc.origin == "support_ticket" and esc.risk_level == RiskLevel.RESTRICTED
    await tickets.act(db, admin, t.id, "raise_incident", body="Possible session fixation")
    assert t.incident_id
    with pytest.raises(tickets.TicketError, match="resolution"):
        await tickets.act(db, risk, t.id, "resolve")
    await tickets.act(db, risk, t.id, "resolve", body="IdP redirect fixed")
    view = await tickets.register(db, "t1")
    assert view["tickets"][0]["ref"].startswith("SUP-") and view["summary"]["open"] == 0
    assert (await tickets.register(db, "t2"))["tickets"] == []


async def test_legacy_ticket_still_reads(db) -> None:
    db.add(SupportTicket(id="old", tenant_id="t1", category="accuracy", severity="P0", status="Open", created_by="admin",
                         created_at=NOW))
    await db.commit()
    v = (await tickets.register(db, "t1"))["tickets"][0]
    assert v["priority"] == "P1" and v["status"] == "open" and v["subject"] == "Accuracy request"


async def test_incident_rules(db) -> None:
    admin, admin2 = await _u(db, "admin"), await _u(db, "admin2")
    event = await record_event_async(db, tenant_id="t1", event_name="access_denied", emitting_service="identity",
                                     actor_id="learner", subject_type="permission", subject_id="admin", payload={})
    inc = await incidents.create(db, admin, title="Cross-tenant read attempt", severity="Critical", source="AUDIT_EVENT",
                                 note="Opened from audit", event_id=event.id)
    await incidents.act(db, admin, inc.id, "assign", owner_id="admin")
    with pytest.raises(incidents.IncidentError, match="containment"):
        await incidents.act(db, admin, inc.id, "contain")
    await incidents.act(db, admin, inc.id, "contain", note="Token revoked")
    with pytest.raises(incidents.IncidentError, match="someone other"):
        await incidents.act(db, admin, inc.id, "resolve", note="Done")
    with pytest.raises(incidents.IncidentError, match="not found"):
        await incidents.act(db, admin, inc.id, "link_event", event_id="nope")
    await incidents.act(db, admin2, inc.id, "resolve", note="Policy corrected")
    view = (await incidents.register(db, "t1"))["incidents"][0]
    assert view["status"] == "RESOLVED" and view["linkedEventIds"] == [event.id]
    assert [e["actor"] for e in view["timeline"]][-1] == "Admin2"


def test_audit_classification() -> None:
    assert audit.classify("access_denied") == ("access", "high", "denied")
    assert audit.classify("tenant_setting_override_prohibited")[0] == "access"
    assert audit.classify("break_glass_access_granted") == ("privileged", "critical", "recorded")
    assert audit.classify("query_received") == ("ai", "low", "recorded")
    assert audit.classify("refusal_returned")[2] == "blocked"
    assert audit.classify("source_version_approved")[0] == "source"
    assert audit.classify("licence_prefilter_completed")[0] == "ai"


async def test_audit_events_traces_and_controlled_export(db) -> None:
    admin, admin2 = await _u(db, "admin"), await _u(db, "admin2")
    for name in ("query_received", "response_returned", "access_denied"):
        await record_event_async(db, tenant_id="t1", event_name=name, emitting_service="test", actor_id="admin",
                                 subject_type="query", subject_id="q9", correlation_id="q9",
                                 payload={"secret": "customer text"})
    denied = await audit.events(db, "t1", family="access")
    assert [e["event"] for e in denied["events"]] == ["access_denied"]
    traces = await audit.traces(db, "t1")
    assert traces["traces"][0]["correlationId"] == "q9" and traces["traces"][0]["complete"]

    x = await audit.request_export(db, admin, "Quarterly access review evidence", {"family": "access"})
    with pytest.raises(audit.ExportError, match="different Admin"):
        await audit.decide_export(db, admin, x.id, True, "")
    with pytest.raises(audit.ExportError, match="not approved"):
        await audit.export_csv(db, admin, x.id)
    await audit.decide_export(db, admin2, x.id, True, "Approved for the review")
    name, content = await audit.export_csv(db, admin, x.id)
    assert name.endswith(".csv") and "access_denied" in content and "customer text" not in content
    assert "query_received" not in content, "only the approved filter is exported"
