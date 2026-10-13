"""Governance Dashboard reads the tenant's real governance records.

Pins the dashboard's contract with the Admin Governance Console spec §4 and
its one hard rule — never show a value the platform did not measure:
  * an empty tenant is "not assessed", never a healthy-looking zero;
  * health cards, alerts, work queue and release gates come from live rows;
  * other tenants' incidents/escalations never leak into the counts;
  * the work queue is role-filtered and flags the viewer's own submissions;
  * Learners have no governance view.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.evaluation.models import EvaluationRun, ResultPack
from app.domains.governance_dashboard.router import get_governance_dashboard
from app.domains.identity.models import BreakGlassGrant, Tenant, User
from app.domains.risk_safety.models import EscalationCase, EscalationStatus, RiskLevel, RiskPolicy
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident
from app.orchestration.models import ReviewCase

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


def _user(uid: str, tenant: str, role: str) -> User:
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", first_name=uid, last_name="",
                full_name=uid, role=role, is_active=True)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme Ltd"), Tenant(id="t2", name="Other Co"),
            _user("admin", "t1", "Admin"), _user("source-admin", "t1", "Source Admin"),
            _user("auditor", "t1", "System Auditor"), _user("learner", "t1", "Learner"),
            _user("admin-b", "t2", "Admin"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _dashboard(db, uid: str) -> dict:
    user = await db.get(User, uid)
    return await get_governance_dashboard(environment="PRODUCTION", window_days=30, db=db, current_user=user)


def _domain(model: dict, key: str) -> dict:
    return next(d for d in model["domainStates"] if d["key"] == key)


async def _seed_governance_records(db) -> None:
    db.add_all([
        Source(id="s-ok", tenant_id="t1", category="tax", title="VAT Notice", source_class="primary",
               is_tenant_private=True, licence_state="permitted"),
        Source(id="s-exp", tenant_id="t1", category="tax", title="FRS 102", source_class="primary",
               is_tenant_private=True, licence_state="permitted"),
        Source(id="s-unk", tenant_id="t1", category="audit", title="Internal memo", source_class="internal",
               is_tenant_private=True, licence_state="unknown"),
        SourceVersion(id="v-ok", source_id="s-ok", tenant_id="t1", status="ACTIVE", submitted_by="admin"),
        SourceVersion(id="v-exp", source_id="s-exp", tenant_id="t1", status="ACTIVE", submitted_by="admin",
                      effective_to=TODAY + timedelta(days=10)),
        SourceVersion(id="v-new", source_id="s-unk", tenant_id="t1", status="PROPOSED", submitted_by="source-admin"),
        RiskPolicy(id="pol-1", version="1.0", rules=[{"r": 1}], approver=None),
        EscalationCase(id="ESC-late", tenant_id="t1", query_id="q1", query_text="?", topic="tax",
                       risk_level=RiskLevel.HIGH, status=EscalationStatus.PENDING, reviewer_role="Risk Admin",
                       sla_deadline=(NOW - timedelta(hours=2)).replace(tzinfo=None)),
        EscalationCase(id="ESC-other", tenant_id="t2", query_id="q2", query_text="?", topic="tax",
                       risk_level=RiskLevel.HIGH, status=EscalationStatus.PENDING,
                       sla_deadline=(NOW - timedelta(hours=2)).replace(tzinfo=None)),
        SecurityIncident(id="inc-1", tenant_id="t1", title="Prompt bypass attempt", severity="Critical",
                         source="CONTROL_BYPASS"),
        SecurityIncident(id="inc-2", tenant_id="t2", title="Other tenant incident", severity="Critical",
                         source="CONTROL_BYPASS"),
        ReviewCase(id="rc-1", query_id="q3", correlation_id="q3", tenant_id="t1", risk_level="HIGH",
                   confidence_state="limited", reason="conflict", status="open", query_text="Is this deductible?"),
        BreakGlassGrant(id="bg-1", tenant_id="t1", user_id="auditor", permissions=["audit.correct"], reason="x",
                        duration_minutes=30, status="expired", ended_at=NOW),
    ])
    await db.commit()


async def test_empty_tenant_is_not_assessed_not_healthy(db) -> None:
    model = await _dashboard(db, "admin")
    assert _domain(model, "source_approval")["state"] == "not_assessed"
    assert _domain(model, "licence_status")["state"] == "not_assessed"
    assert _domain(model, "risk_policy")["state"] == "not_assessed"
    assert _domain(model, "jurisdiction_readiness")["reason"]
    assert model["exceptions"] == []
    gates = {g["gate"]: g["state"] for g in model["releaseReadiness"]}
    assert gates["Evaluation"] == "blocked", "no evaluation run must block, not pass"


async def test_dashboard_reflects_real_records(db) -> None:
    await _seed_governance_records(db)
    model = await _dashboard(db, "admin")

    approval = _domain(model, "source_approval")
    assert approval["state"] == "attention"
    assert {m["label"]: m["value"] for m in approval["metrics"]}["Awaiting approval"] == 1

    licence = _domain(model, "licence_status")
    assert licence["state"] == "attention"
    assert {m["label"]: m["value"] for m in licence["metrics"]}["Unknown"] == 1

    assert _domain(model, "risk_policy")["state"] == "attention"  # no named approver
    assert _domain(model, "escalation_sla")["state"] == "critical"
    assert _domain(model, "incidents")["state"] == "critical"
    assert _domain(model, "audit_ledger")["state"] == "effective"

    kinds = [a["id"].split(":")[0] for a in model["exceptions"]]
    assert kinds[0] == "incident", "critical alerts sort first"
    assert {"incident", "escalation", "risk-policy", "licence", "licence-unknown", "break-glass"} <= set(kinds)
    assert all(a["ownerRole"] for a in model["exceptions"]), "every alert names an owner"
    late = next(a for a in model["exceptions"] if a["id"] == "escalation:ESC-late")
    assert late["dueAt"] and late["ownerRole"] == "Risk Admin"

    summary = model["governanceSummary"]
    assert summary["overallState"] == "critical"
    assert summary["criticalExceptionCount"] == 1
    gates = {g["gate"]: g["state"] for g in model["releaseReadiness"]}
    assert gates["Security incidents"] == "blocked" and gates["Risk policy approval"] == "blocked"
    assert gates["Audit ledger"] == "passed"


async def test_other_tenants_never_counted(db) -> None:
    await _seed_governance_records(db)
    model = await _dashboard(db, "admin")
    assert all("Other tenant" not in a["title"] for a in model["exceptions"])
    assert "escalation:ESC-other" not in {a["id"] for a in model["exceptions"]}
    incidents = {m["label"]: m["value"] for m in _domain(model, "incidents")["metrics"]}
    assert incidents["Critical"] == 1

    other = await _dashboard(db, "admin-b")
    assert {m["label"]: m["value"] for m in _domain(other, "incidents")["metrics"]}["Critical"] == 1
    assert _domain(other, "source_approval")["state"] == "not_assessed", "t1's private sources stay private"


async def test_work_queue_is_role_filtered_and_flags_own_submissions(db) -> None:
    await _seed_governance_records(db)
    admin_queue = {d["type"] for d in (await _dashboard(db, "admin"))["decisions"]}
    assert {"Source approval", "Answer review", "Escalation"} <= admin_queue

    source_admin = (await _dashboard(db, "source-admin"))["decisions"]
    assert {d["type"] for d in source_admin} == {"Source approval"}
    assert source_admin[0]["blockedReason"], "own submission needs a second approver"

    assert (await _dashboard(db, "auditor"))["decisions"] == [], "read-only role has nothing to approve"


async def test_another_tenants_shared_submission_is_not_this_tenants_decision(db) -> None:
    db.add_all([
        Source(id="s-shared", tenant_id="t2", category="audit", title="Shared practice aid",
               source_class="secondary", is_tenant_private=False),
        SourceVersion(id="v-shared-new", source_id="s-shared", tenant_id="t2", status="PROPOSED", submitted_by="admin-b"),
    ])
    await db.commit()
    model = await _dashboard(db, "admin")
    assert all("Shared practice aid" not in d["title"] for d in model["decisions"])
    approval = _domain(model, "source_approval")
    assert {m["label"]: m["value"] for m in approval["metrics"]}["Awaiting approval"] == 0
    # …while the submitting tenant does see it.
    assert any("Shared practice aid" in d["title"] for d in (await _dashboard(db, "admin-b"))["decisions"])


async def test_seed_approver_is_not_a_named_approver(db) -> None:
    db.add(RiskPolicy(id="pol-seed", version="v1", rules=[], approver="system-init"))
    await db.commit()
    model = await _dashboard(db, "admin")
    policy = _domain(model, "risk_policy")
    assert policy["state"] == "attention"
    assert {m["label"]: m["value"] for m in policy["metrics"]}["Approver"] == "No named approver"
    assert any(a["id"] == "risk-policy:pol-seed" for a in model["exceptions"])


async def test_release_gates_follow_measured_evidence(db) -> None:
    await _seed_governance_records(db)
    gates = {g["gate"]: g for g in (await _dashboard(db, "admin"))["releaseReadiness"]}
    assert gates["Escalation SLA"]["state"] == "blocked"
    assert gates["Source licensing"]["state"] == "passed", "expiring-soon warns but does not block"
    assert gates["Rollback point"]["state"] == "not_assessed"

    db.add_all([
        EvaluationRun(id="run-1", dataset_id="ds", threshold_set_id="ts", config_hash="h", status="COMPLETED"),
        ResultPack(id="pack-1", run_id="run-1", exact_config_hash="h", contamination_scan_status="PASSED",
                   zero_tolerance_passed=True, promotion_eligible=True),
    ])
    await db.commit()
    gates = {g["gate"]: g for g in (await _dashboard(db, "admin"))["releaseReadiness"]}
    assert gates["Evaluation"]["state"] == "passed"

    db.add_all([
        EvaluationRun(id="run-2", dataset_id="ds", threshold_set_id="ts", config_hash="h", status="COMPLETED",
                      created_at=datetime.now() + timedelta(minutes=1)),
        ResultPack(id="pack-2", run_id="run-2", exact_config_hash="h", contamination_scan_status="FAILED",
                   zero_tolerance_passed=True, promotion_eligible=False),
    ])
    await db.commit()
    evaluation = {g["gate"]: g for g in (await _dashboard(db, "admin"))["releaseReadiness"]}["Evaluation"]
    assert evaluation["state"] == "blocked" and "contamination" in evaluation["reason"]


async def test_learners_have_no_governance_view(db) -> None:
    with pytest.raises(HTTPException) as exc:
        await _dashboard(db, "learner")
    assert exc.value.status_code == 403


async def test_governance_roles_are_allowed(db) -> None:
    model = await _dashboard(db, "auditor")
    assert model["governanceScope"]["workspaceName"] == "Acme Ltd"
