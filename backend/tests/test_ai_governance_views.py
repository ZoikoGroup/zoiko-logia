"""AI Governance pages: safety summary, enforced policy, professional
boundaries — computed from the tenant's own ledgers."""
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import get_db, get_sync_db
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.risk_safety.models import (
    EscalationCase, EscalationRule, RestrictedTopicRule, RiskPolicy, SafetyEvent, SafetyOverride, _utcnow,
)
from app.domains.risk_safety.router import router


def _audit(tenant: str, name: str, payload: dict, n: int = 0) -> AuditEvent:
    return AuditEvent(
        id=f"{tenant}-{name}-{n}", event_name=name, emitting_service="orchestration", tenant_id=tenant,
        subject_type="query", subject_id=f"q-{n}", payload=payload, payload_hash="h", chain_hash=f"c-{tenant}-{name}-{n}",
    )


@pytest.fixture
def governance_app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (EscalationCase, SafetyEvent, SafetyOverride, RiskPolicy, EscalationRule, RestrictedTopicRule, AuditEvent):
        model.__table__.create(engine)
    now = _utcnow().replace(tzinfo=None)
    with Session(engine) as db:
        for tenant in ("a", "b"):
            db.add(EscalationCase(id=f"esc-{tenant}", tenant_id=tenant, query_id="q", query_text="q", topic="Tax",
                                  risk_level="HIGH", sla_deadline=now - timedelta(hours=1)))
            db.add(SafetyEvent(tenant_id=tenant, event_type="risk_classification_applied",
                               payload={"risk_level": "HIGH"}, timestamp=now))
            db.add(SafetyEvent(tenant_id=tenant, event_type="risk_classification_applied",
                               payload={"risk_level": "LOW"}, timestamp=now - timedelta(days=20)))
            db.add(SafetyEvent(tenant_id=tenant, event_type="restricted_topic_blocked",
                               payload={"restricted_sub_class": "RESTRICTED_ACADEMIC_INTEGRITY"}, timestamp=now))
            db.add(_audit(tenant, "response_returned", {}))
            db.add(_audit(tenant, "security_incident_recorded", {}))
            db.add(_audit(tenant, "refusal_returned", {"reason": "Professional tax certification requested"}))
            db.add(_audit(tenant, "composition_rejected", {
                "failures": [
                    "Prohibited-claim detected: answer contains professional-advice language matching pattern 'x'.",
                    "Rejected: \"some claim\"",
                ],
                "degraded_route": "REFUSAL",
            }))
        # Tenant b has extra activity that must never show up for tenant a.
        for n in range(1, 4):
            db.add(_audit("b", "response_returned", {}, n))
        db.add(RiskPolicy(id="pol-1", version="v1", rules=[{"pattern": "x", "risk": "HIGH"}]))
        db.add(EscalationRule(id="rule-high", trigger_condition="HIGH", reviewer_role="SME Reviewer",
                              sla_hours=4, severity="Medium", notification_path="email"))
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_sync_db] = lambda: db

        async def unused_auth_db():
            yield None

        app.dependency_overrides[get_db] = unused_auth_db
        user = User(id="lead", tenant_id="a", role="Risk Admin", email="lead@example.com", is_active=True)
        yield app, user
    engine.dispose()


async def _get(app, path, method="GET", json=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, "/safety" + path, json=json)


@pytest.mark.parametrize("method,path", [
    ("GET", "/summary"), ("GET", "/policy"), ("GET", "/boundaries"), ("POST", "/boundaries/check"),
])
async def test_views_require_sign_in(governance_app, method, path):
    app, _ = governance_app
    response = await _get(app, path, method, {"text": "hello"} if method == "POST" else None)
    assert response.status_code == 401


async def test_summary_counts_the_whole_tenant_ledger(governance_app):
    app, user = governance_app
    app.dependency_overrides[get_current_user] = lambda: user
    body = (await _get(app, "/summary")).json()
    assert body["totals"]["events"] == 3
    assert body["totals"]["classified"] == 2
    assert body["totals"]["blocked"] == 1
    assert body["totals"]["incidents"] == 1
    assert body["last_7_days"]["classified"] == 1
    assert body["risk_levels"] == {"HIGH": 1, "LOW": 1, "RESTRICTED": 1}
    assert body["answer_outcomes"]["answered"] == 1  # tenant b's three are excluded
    assert body["escalations"]["total"] == 1 and body["escalations"]["over_sla"] == 1
    assert len(body["trend"]) == 14 and body["trend"][-1]["classified"] == 1


async def test_policy_reports_enforced_rules(governance_app):
    app, user = governance_app
    app.dependency_overrides[get_current_user] = lambda: user
    body = (await _get(app, "/policy")).json()
    assert body["policy"]["version"] == "v1"
    assert body["routing_matrix"]["HIGH"]["LOW_CONFIDENCE"]["route"] == "HUMAN_REVIEW"
    assert body["escalation_rules"][0]["reviewer_role"] == "SME Reviewer"
    academic = next(s for s in body["restricted_subclasses"] if s["code"] == "RESTRICTED_ACADEMIC_INTEGRITY")
    assert academic["blocked_count"] == 1 and academic["patterns"]


async def test_boundaries_count_live_rejections_by_check(governance_app):
    app, user = governance_app
    app.dependency_overrides[get_current_user] = lambda: user
    body = (await _get(app, "/boundaries")).json()
    assert body["counts"]["answers_rejected"] == 1
    assert body["counts"]["certification_refusals"] == 1
    assert body["rejections_by_check"] == [
        {"key": "prohibited_claim", "label": "Professional-advice wording", "count": 1},
    ]
    assert any(rule["check"] == "Prohibited professional claim" for rule in body["rules"])


async def test_boundary_check_runs_the_live_validator(governance_app):
    app, user = governance_app
    app.dependency_overrides[get_current_user] = lambda: user
    safe = (await _get(app, "/boundaries/check", "POST", {"text": "IFRS 16 requires lessees to recognise a lease liability."})).json()
    assert safe["passed"] is True and safe["outcome"] == "released"

    directive = {"text": "You must file your return by January.", "user_specific": True}
    assert (await _get(app, "/boundaries/check", "POST", directive)).json()["outcome"] == "refused"
    directive["user_specific"] = False
    assert (await _get(app, "/boundaries/check", "POST", directive)).json()["passed"] is True

    hedging = {"text": "This is definitely deductible.", "confidence_state": "limited"}
    assert (await _get(app, "/boundaries/check", "POST", hedging)).json()["outcome"] == "human_review"
