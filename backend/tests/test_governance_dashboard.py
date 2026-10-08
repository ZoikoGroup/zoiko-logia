"""Governance Dashboard exceptions, decisions and domain states come from
Kriton's own records, tenant-scoped and permission-bound
(app/domains/governance_dashboard/service.py)."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.evaluation.models import EvaluationRun, ResultPack
from app.domains.governance_dashboard.service import (
    ACCOUNTABILITY, AI_SAFETY, AUDIT_INCIDENT, BOUNDARIES, EVALUATION, JURISDICTION, SOURCE_GOV,
    build_governance_dashboard,
)
from app.domains.identity.models import Tenant, User
from app.domains.model_gateway.models import PromptTemplate
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RestrictedSubClass, RiskLevel
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
NAIVE_NOW = NOW.replace(tzinfo=None)


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


def _user(role="Admin", tenant_id="t1") -> User:
    return User(id=f"u-{role}", tenant_id=tenant_id, email=f"{role}@example.com", full_name=role, role=role)


def _escalation(case_id, tenant_id="t1", risk=RiskLevel.HIGH, sla=None, sub_class=None, status=EscalationStatus.PENDING):
    return EscalationCase(id=case_id, tenant_id=tenant_id, query_id=f"q-{case_id}", query_text="Can I skip the audit?",
                          topic=f"Topic {case_id}", risk_level=risk, restricted_sub_class=sub_class,
                          status=status, sla_deadline=sla, created_at=NAIVE_NOW - timedelta(days=1))


def _domain(panels, name):
    return next(d for d in panels["domainStates"] if d["name"] == name)


async def test_records_become_exceptions_in_the_right_domains(db):
    user = _user()
    db.add_all([
        user,
        _escalation("overdue", sla=NAIVE_NOW - timedelta(hours=3)),
        _escalation("boundary", risk=RiskLevel.RESTRICTED, sub_class=RestrictedSubClass.CONTROL_BYPASS),
        _escalation("high", risk=RiskLevel.HIGH),
        _escalation("low", risk=RiskLevel.LOW),                       # open but not an exception
        SecurityIncident(id="inc-1", tenant_id="t1", title="PII in an upload", severity="Critical",
                         containment_status="OPEN", source="PII_LEAK"),
        Source(id="s1", tenant_id="t1", category="Tax", title="HMRC VAT manual", source_class="primary"),
        SourceVersion(id="v1", tenant_id="t1", source_id="s1", status="APPROVED", submitted_by="u-Admin",
                      effective_to=date(2026, 10, 18)),
    ])
    await db.commit()

    panels = await build_governance_dashboard(db, user, NOW)

    by_id = {e["id"]: e for e in panels["exceptions"]}
    assert by_id["overdue"]["domain"] == ACCOUNTABILITY and by_id["overdue"]["severity"] == "Critical"
    assert by_id["boundary"]["domain"] == BOUNDARIES
    assert by_id["high"]["domain"] == AI_SAFETY
    assert "low" not in by_id
    assert by_id["inc-1"]["domain"] == AUDIT_INCIDENT and by_id["inc-1"]["severity"] == "Critical"
    assert by_id["v1"]["domain"] == SOURCE_GOV and "10 days left" in by_id["v1"]["detail"]
    assert [e["severity"] for e in panels["exceptions"]][:2] == ["Critical", "Critical"]   # critical first
    summary = panels["governanceSummary"]
    assert summary["criticalExceptionCount"] == 2 and summary["highExceptionCount"] == 3
    assert summary["overallState"] == "attention_required"
    assert panels["sourceGovernance"]["expiringWithin30Days"] == 1
    assert panels["incidents"]["openIncidentCounts"]["critical"] == 1
    assert _domain(panels, AI_SAFETY)["state"] == "attention_required"
    assert _domain(panels, EVALUATION)["state"] == "no_open_exceptions"
    assert _domain(panels, JURISDICTION)["state"] == "not_assessed"


async def test_no_records_is_no_open_exceptions_never_effective(db):
    user = _user()
    db.add(user)
    await db.commit()

    panels = await build_governance_dashboard(db, user, NOW)

    assert panels["exceptions"] == [] and panels["decisions"] == []
    assert panels["governanceSummary"]["overallState"] == "no_open_exceptions"
    states = {d["state"] for d in panels["domainStates"]}
    assert "effective" not in states and states <= {"no_open_exceptions", "not_assessed"}


async def test_other_tenants_and_resolved_records_are_ignored(db):
    user = _user()
    db.add_all([
        user,
        _escalation("other", tenant_id="t2", sla=NAIVE_NOW - timedelta(days=1)),
        _escalation("done", status=EscalationStatus.RESOLVED, sla=NAIVE_NOW - timedelta(days=1)),
        SecurityIncident(id="inc-other", tenant_id="t2", title="Other", severity="Critical",
                         containment_status="OPEN", source="PII_LEAK"),
        SecurityIncident(id="inc-closed", tenant_id="t1", title="Closed", severity="Critical",
                         containment_status="RESOLVED", source="PII_LEAK"),
    ])
    await db.commit()

    panels = await build_governance_dashboard(db, user, NOW)

    assert panels["exceptions"] == []


async def test_pending_decisions_follow_the_roles_manage_permissions(db):
    admin, auditor = _user("Admin"), _user("System Auditor")
    db.add_all([
        admin, auditor,
        ReviewCase(id="rc1", query_id="q", correlation_id="c", tenant_id="t1", query_text="VAT on vouchers?",
                   risk_level="HIGH", confidence_state="LOW", reason="r", status="open"),
        _escalation("pending", risk=RiskLevel.MEDIUM),
        PromptTemplate(id="p1", name="tax_answer", version="v2", status="PendingReview", submitted_by="u-Admin"),
        Source(id="s2", tenant_id="t1", category="Audit", title="ISA 315", source_class="primary"),
        SourceVersion(id="v2", tenant_id="t1", source_id="s2", status="PROPOSED", submitted_by="u-Admin", version_label="v3"),
    ])
    await db.commit()

    admin_view = await build_governance_dashboard(db, admin, NOW)
    kinds = {d["kind"] for d in admin_view["decisions"]}
    assert kinds == {"ANSWER REVIEW", "ESCALATION", "PROMPT APPROVAL", "SOURCE APPROVAL"}
    assert admin_view["governanceSummary"]["pendingDecisionCount"] == 4

    # The auditor reads but never decides: no decisions, but still sees reads.
    auditor_view = await build_governance_dashboard(db, auditor, NOW)
    assert auditor_view["decisions"] == [] and auditor_view["governanceSummary"]["pendingDecisionCount"] == 0
    assert auditor_view["accountability"]["mandatoryReviews"] == 1


async def test_blocked_release_gate_and_unsigned_eligible_release(db):
    user = _user()
    db.add_all([
        user,
        EvaluationRun(id="run-bad", dataset_id="d", threshold_set_id="t", config_hash="h1", status="COMPLETED",
                      created_at=NAIVE_NOW - timedelta(hours=2)),
        ResultPack(id="pack-bad", run_id="run-bad", exact_config_hash="h1", zero_tolerance_passed=False,
                   promotion_eligible=False),
        EvaluationRun(id="run-ok", dataset_id="d", threshold_set_id="t", config_hash="h2", status="COMPLETED",
                      created_at=NAIVE_NOW - timedelta(hours=1)),
        ResultPack(id="pack-ok", run_id="run-ok", exact_config_hash="h2", promotion_eligible=True),
    ])
    await db.commit()

    panels = await build_governance_dashboard(db, user, NOW)

    assert [r["runId"] for r in panels["releaseReadiness"]] == ["run-ok", "run-bad"]
    assert panels["governanceSummary"]["blockedGateCount"] == 1
    assert any(e["domain"] == EVALUATION and "zero-tolerance" in e["title"] for e in panels["exceptions"])
    assert any(d["kind"] == "RELEASE" and d["id"] == "pack-ok" for d in panels["decisions"])


async def test_roles_without_a_permission_see_restricted_domains(db):
    user = _user("Source Admin")          # source.read / source.manage only
    db.add_all([user, _escalation("hidden", sla=NAIVE_NOW - timedelta(days=1))])
    await db.commit()

    panels = await build_governance_dashboard(db, user, NOW)

    assert panels["exceptions"] == []
    assert _domain(panels, SOURCE_GOV)["state"] == "no_open_exceptions"
    for name in (AI_SAFETY, EVALUATION, AUDIT_INCIDENT, BOUNDARIES, ACCOUNTABILITY):
        assert _domain(panels, name)["state"] == "restricted"
