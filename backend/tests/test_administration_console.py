"""Administration console: tenant policy, access reviews and offboarding,
the role registry view, release gates, service accounts and entities.

Pins the governance rules: a tenant can only tighten a setting and only with a
second Admin's approval, and the tightened value is what is enforced; nobody
certifies their own access; offboarding is complete only when nothing is
owned or held; a release reaches production only with every gate passed and
another person's approval; and tenants stay isolated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.admin_governance import access, elevated, releases, tenant_policy
from app.domains.identity import governance, rbac
from app.domains.identity.models import (
    Engagement, EngagementMembership, ServiceAccount, ServiceAccountKey, Tenant, User,
)
from app.domains.operations.models import ProviderRecord

NOW = datetime.now(timezone.utc)


def _user(uid, tenant, role, active=True, created=None):
    return User(id=uid, tenant_id=tenant, email=f"{uid}@example.com", first_name=uid, last_name="",
                full_name=uid.title(), role=role, is_active=active, created_at=created or NOW - timedelta(days=200))


@pytest.fixture
async def db(monkeypatch):
    async def _no_auth(_ids):
        return {}
    monkeypatch.setattr(access, "_auth_status", _no_auth)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme"), Tenant(id="t2", name="Other"),
            _user("admin", "t1", "Admin"), _user("admin2", "t1", "Admin"), _user("risk", "t1", "Risk Admin"),
            _user("learner", "t1", "Learner", created=NOW - timedelta(days=10)),
            _user("leaver", "t1", "SME Reviewer", active=False), _user("svc", "t1", "System Auditor"),
            _user("b-admin", "t2", "Admin"),
            ServiceAccount(id="svc", tenant_id="t1", name="erp-sync", owner_user_id="leaver", created_by="admin"),
            ServiceAccountKey(id="k1", service_account_id="svc", tenant_id="t1", key_prefix="zlk_abc",
                              key_hash="h", created_by="admin", expires_at=NOW + timedelta(days=3)),
            ProviderRecord(id="p1", tenant_id="t1", ref="PRV-001", name="Groq", category="ai_model",
                           owner_user_id="leaver", created_by="admin", gates={}),
            Engagement(id="e1", tenant_id="t1", name="Northstar audit FY26"),
            EngagementMembership(id="m1", tenant_id="t1", engagement_id="e1", user_id="risk"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _get(db, uid):
    return await db.get(User, uid)


# ── Tenant policy ──────────────────────────────────────────────────────────

async def test_tenant_can_only_tighten_and_needs_a_second_admin(db) -> None:
    admin, admin2 = await _get(db, "admin"), await _get(db, "admin2")
    with pytest.raises(tenant_policy.PolicyError, match="Prohibited override"):
        await tenant_policy.request_change(db, admin, "impersonation_max_minutes", 600, "longer sessions")
    with pytest.raises(tenant_policy.PolicyError, match="not tenant-adjustable"):
        await tenant_policy.request_change(db, admin, "public_signup", True, "x")

    req = await tenant_policy.request_change(db, admin, "impersonation_max_minutes", 15, "Shorter view-as sessions")
    assert req.ref == "CHG-001" and req.status == "pending"
    assert await tenant_policy.effective(db, "t1", "impersonation_max_minutes") == 60, "not effective until approved"
    with pytest.raises(tenant_policy.PolicyError, match="different Admin"):
        await tenant_policy.decide(db, admin, req.id, True, "")
    await tenant_policy.decide(db, admin2, req.id, True, "Agreed")
    assert req.status == "applied"
    assert await tenant_policy.effective(db, "t1", "impersonation_max_minutes") == 15
    assert await tenant_policy.effective(db, "t2", "impersonation_max_minutes") == 60, "other tenants unaffected"

    # The tightened limit is what governance enforces.
    with pytest.raises(governance.GovernanceError, match="between 1 and 15"):
        await governance.start_impersonation(db, admin, "learner", "check", 30)


async def test_tenant_mfa_requirement_is_enforced(db, monkeypatch) -> None:
    admin, admin2 = await _get(db, "admin"), await _get(db, "admin2")
    monkeypatch.setattr(rbac.get_settings(), "MFA_REQUIRED_FOR_PRIVILEGED", False)
    await rbac.enforce_step_up(db, admin, "admin")  # not required yet
    req = await tenant_policy.request_change(db, admin, "mfa_required_privileged", True, "Policy")
    await tenant_policy.decide(db, admin2, req.id, True, "")
    with pytest.raises(HTTPException) as exc:
        await rbac.enforce_step_up(db, admin, "admin")
    assert exc.value.status_code == 403
    admin.auth_aal = "aal2"
    await rbac.enforce_step_up(db, admin, "admin")


# ── Users, reviews and offboarding ─────────────────────────────────────────

async def test_access_reviews_and_offboarding(db) -> None:
    admin, admin2 = await _get(db, "admin"), await _get(db, "admin2")
    with pytest.raises(access.AccessError, match="own access"):
        await access.record_review(db, admin, "admin", "certified", "")
    view = await access.users_view(db, "t1")
    members = {m["id"]: m for m in view["members"]}
    assert "svc" not in members, "service accounts are not people"
    assert members["admin"]["reviewOverdue"], "privileged role never reviewed in 200 days"
    assert not members["learner"]["reviewOverdue"], "a standard role is reviewed quarterly"
    leaver = members["leaver"]
    assert leaver["status"] == "offboarding"
    labels = " ".join(b["label"] for b in leaver["blockers"])
    assert "erp-sync" in labels and "PRV-001" in labels
    gates = {g["label"]: g["status"] for g in leaver["offboardingGates"]}
    assert gates["Delegated credentials revoked"] == "open" and gates["Resource ownership transferred"] == "open"

    await access.record_review(db, admin2, "admin", "certified", "")
    view = await access.users_view(db, "t1")
    assert not {m["id"]: m for m in view["members"]}["admin"]["reviewOverdue"]

    team = await access.create_team(db, admin, "Audit", "", "risk")
    await access.update_team(db, admin, team.id, add=["risk", "learner"])
    with pytest.raises(access.AccessError):
        await access.update_team(db, admin, team.id, add=["b-admin"])
    teams = (await access.users_view(db, "t1"))["teams"]
    assert teams[0]["members"] == 2 and teams[0]["owner"] == "Risk"


async def test_roles_view_reports_real_conflicts_and_tests(db) -> None:
    view = await access.roles_view(db, "t1")
    roles = {r["name"]: r for r in view["roles"]}
    assert roles["Admin"]["sodConflicts"], "Admin holds every permission, so every SoD pair"
    assert not roles["SME Reviewer"]["sodConflicts"]
    assert roles["Admin"]["people"] == 2 and roles["System Auditor"]["serviceAccounts"] == 1
    tests = {t["label"]: t["passed"] for t in view["policyTests"]}
    assert tests["Learner holds no governance permission"] and tests["Service accounts can never hold Admin"]
    assert not tests["No separation-of-duties conflict held by a person"]
    assert access.simulate("Learner", "review.resolve", mfa_required=False, session_mfa=False)["decision"] == "deny"
    assert access.simulate("SME Reviewer", "review.resolve", mfa_required=True, session_mfa=False)["decision"] == "step_up"


# ── Service accounts and entities ──────────────────────────────────────────

async def test_service_account_with_departed_owner_is_quarantined(db) -> None:
    view = await elevated.service_accounts(db, "t1")
    a = view["accounts"][0]
    assert a["state"] == "quarantined" and a["risk"] == "critical"
    assert view["summary"]["ownershipReviews"] == 1 and view["summary"]["renewals"] == 1
    assert (await elevated.service_accounts(db, "t2"))["accounts"] == []


async def test_entities_shows_engagements_and_keeps_the_dpia_hold(db) -> None:
    view = await elevated.entities(db, "t1")
    assert view["engagements"][0]["name"] == "Northstar audit FY26"
    assert view["engagements"][0]["activeMembers"] == 1
    assert view["legalEntityRegister"]["available"] is False


# ── Release gates ──────────────────────────────────────────────────────────

LIVE = {k: {"status": "pass", "note": "measured"} for k in
        ("security_isolation", "licensing_privacy", "ai_evaluation", "operational_readiness")}


async def test_release_needs_every_gate_and_a_second_person(db) -> None:
    risk, admin = await _get(db, "risk"), await _get(db, "admin")
    r = await releases.create(db, risk, {"name": "Agent orchestrator", "version": "2.6.0", "component": "AI Orchestration",
                                         "change_ref": "CHG-711", "description": "New planner", "risk": "high",
                                         "owner_user_id": "risk"})
    view = releases.view(r, LIVE, {})
    assert r.ref == "REL-001" and view["status"] == "validating" and view["passed"] == 5

    with pytest.raises(releases.ReleaseError, match="measured by the platform"):
        await releases.set_gate(db, risk, r.id, "ai_evaluation", "pass", "x")
    for gate in releases.MANUAL:
        await releases.set_gate(db, risk, r.id, gate, "pass", "evidence attached")
    assert releases.view(r, LIVE, {})["status"] == "approval_queue"
    with pytest.raises(releases.ReleaseError, match="someone other"):
        await releases.transition(db, risk, LIVE, r.id, "approve", "")
    with pytest.raises(releases.ReleaseError, match="blocked"):
        await releases.transition(db, admin, LIVE, r.id, "deploy", "")
    await releases.transition(db, admin, LIVE, r.id, "approve", "")
    assert releases.view(r, LIVE, {})["status"] == "approved"

    failing = {**LIVE, "ai_evaluation": {"status": "fail", "note": "citation precision below threshold"}}
    assert releases.view(r, failing, {})["status"] == "on_hold", "a failed live gate holds the release"
    with pytest.raises(releases.ReleaseError):
        await releases.transition(db, admin, failing, r.id, "deploy", "")

    await releases.set_gate(db, risk, r.id, "rollback_evidence", "pass", "rehearsed again")
    assert r.approved_by is None, "changed evidence withdraws the approval"
    await releases.transition(db, admin, LIVE, r.id, "approve", "")
    await releases.transition(db, admin, LIVE, r.id, "deploy", "")
    assert r.status == "deployed"
    with pytest.raises(releases.ReleaseError, match="why"):
        await releases.transition(db, admin, LIVE, r.id, "rollback", "")
    await releases.transition(db, admin, LIVE, r.id, "rollback", "Error rate rose after promotion")
    assert r.status == "rolled_back"
