from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import get_db, get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.risk_safety.models import (
    EscalationCase, SafetyEvent, SafetyOverride, _utcnow,
)
from app.domains.risk_safety.router import router


@pytest.fixture
def safety_app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (EscalationCase, SafetyEvent, SafetyOverride):
        model.__table__.create(engine)
    with Session(engine) as db:
        for tenant in ("a", "b", "GLOBAL_CONTROL"):
            db.add(EscalationCase(id=tenant, tenant_id=tenant, query_id=tenant,
                                  query_text="Private query", topic="Tax", risk_level="HIGH", owner="owner"))
            db.add(SafetyEvent(tenant_id=tenant, event_type="private", payload={"tenant": tenant}))
            db.add(SafetyOverride(tenant_id=tenant, actor_id="owner", authority_role="Admin",
                                  original_route="LLM", new_route="REFUSAL", scope="all", reason="test",
                                  expires_at=_utcnow() + timedelta(hours=1)))
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_sync_db] = lambda: db

        async def unused_auth_db():
            yield None

        app.dependency_overrides[get_db] = unused_auth_db
        user = User(id="reviewer", tenant_id="a", role="Risk Admin", email="reviewer@example.com", is_active=True)
        yield app, db, user
    engine.dispose()


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/events", None), ("GET", "/escalations", None),
    ("GET", "/escalations/stats", None), ("GET", "/overrides", None),
    ("GET", "/policies", None), ("GET", "/templates", None),
    ("POST", "/classify", {"query": "hello"}),
    ("POST", "/validate-output", {"text": "hello"}),
    ("POST", "/escalations/a/action", {"action": "approve", "reviewer_id": "fake"}),
    ("POST", "/overrides", {}),
])
async def test_anonymous_requests_are_rejected(safety_app, method, path, payload):
    app, _, _ = safety_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/safety" + path, json=payload)
    assert response.status_code == 401


async def test_tenant_reads_and_writes_are_isolated(safety_app):
    app, db, user = safety_app
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert [r["id"] for r in (await client.get("/safety/escalations")).json()] == ["a"]
        assert (await client.get("/safety/escalations/stats")).json()["total"] == 1
        assert len((await client.get("/safety/overrides")).json()) == 1
        assert [r["payload"]["tenant"] for r in (await client.get("/safety/events")).json()] == ["a"]
        response = await client.post("/safety/escalations/b/action", json={"action": "approve", "reviewer_id": "fake"})
        assert response.status_code == 404
        response = await client.post("/safety/escalations/a/action", json={"action": "approve", "reviewer_id": "fake"})
        assert response.status_code == 200
        assert response.json()["reviewer_id"] == "reviewer"
        response = await client.post("/safety/overrides", json={
            "actor_id": "fake", "authority_role": "Admin", "original_route": "LLM",
            "new_route": "REFUSAL", "scope": "all", "reason": "test",
        })
        assert response.status_code == 200
        assert response.json()["actor_id"] == "reviewer"
        assert response.json()["authority_role"] == "Risk Admin"
        assert db.get(SafetyOverride, response.json()["id"]).tenant_id == "a"
        assert all(row.tenant_id == "a" for row in db.query(SafetyEvent).filter(SafetyEvent.event_type != "private"))


async def test_maker_checker_uses_authenticated_identity(safety_app):
    app, _, user = safety_app
    user.id = "owner"
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/safety/escalations/a/action", json={"action": "approve", "reviewer_id": "someone-else"})
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["System Auditor", "Learner", "Unknown"])
async def test_read_only_and_unknown_roles_cannot_write(safety_app, role):
    app, _, user = safety_app
    user.role = role
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/safety/escalations/a/action", json={"action": "approve", "reviewer_id": "fake"})
        assert response.status_code == 403
        response = await client.post("/safety/overrides", json={
            "actor_id": "fake", "authority_role": "Admin", "original_route": "LLM",
            "new_route": "REFUSAL", "scope": "all", "reason": "test",
        })
        assert response.status_code == 403
        response = await client.get("/safety/events")
        assert response.status_code == (200 if role == "System Auditor" else 403)


async def test_classification_persists_verified_tenant_and_owner(safety_app, monkeypatch):
    app, db, user = safety_app
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("app.domains.risk_safety.risk_classifier.classify", lambda **kwargs: {
        "query_id": "new-query", "allowed": True, "risk_level": "HIGH", "route": "HUMAN_REVIEW",
        "confidence": 1.0, "requires_human_review": True, "rules_applied": [],
    })
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/safety/classify", json={
            "query": "Review this", "tenant_id": "b", "user_id": "fake", "role": "Admin",
        })
    assert response.status_code == 200
    case = db.query(EscalationCase).filter_by(query_id="new-query").one()
    assert (case.tenant_id, case.owner) == ("a", "reviewer")
    assert all(row.tenant_id == "a" for row in db.query(SafetyEvent).filter_by(query_id="new-query"))
