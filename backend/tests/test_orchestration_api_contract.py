from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.orchestration.router as router_module
from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import (
    AskKritonResponse,
    AuditReference,
    ComposedAnswer,
    SafetyState,
)


def _test_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router_module.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_sync_db] = lambda: object()
    return app


def _answer() -> AskKritonResponse:
    return AskKritonResponse(
        query_id="qry-contract",
        correlation_id="corr-contract",
        outcome="answered",
        route="LLM",
        safety=SafetyState(
            risk_level="LOW",
            policy_state="allowed",
            disclaimer_required=False,
        ),
        confidence_state="sufficient",
        answer=ComposedAnswer(text="Contract response"),
        audit_reference=AuditReference(audit_chain_id="audit-contract"),
    )


def test_ask_endpoint_rejects_unauthenticated_requests():
    with TestClient(_test_app()) as client:
        response = client.post(
            "/api/v1/orchestration/ask",
            headers={"Idempotency-Key": "contract-unauthenticated"},
            json={"query": "Explain accrual accounting."},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_ask_endpoint_uses_authenticated_identity_not_request_fields(monkeypatch):
    app = _test_app()
    authenticated_user = User(
        id="trusted-user",
        tenant_id="trusted-tenant",
        email="trusted@example.test",
        full_name="Trusted User",
        role="Admin",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    captured = {}

    async def resolve_conversation(db, **kwargs):
        captured["conversation"] = kwargs
        return SimpleNamespace(id="conversation-contract")

    async def ask_kriton(db, sync_db, **kwargs):
        captured["orchestration"] = kwargs
        return _answer()

    async def record_turn(db, **kwargs):
        captured["turn"] = kwargs

    monkeypatch.setattr(
        router_module.chat_history_service,
        "resolve_conversation",
        resolve_conversation,
    )
    monkeypatch.setattr(router_module, "ask_kriton", ask_kriton)
    monkeypatch.setattr(
        router_module.chat_history_service,
        "record_turn",
        record_turn,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/orchestration/ask",
            headers={"Idempotency-Key": "contract-authenticated"},
            json={
                "query": "Explain accrual accounting.",
                "tenant_id": "attacker-tenant",
                "user_id": "attacker-user",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == "conversation-contract"
    assert captured["orchestration"]["tenant_id"] == "trusted-tenant"
    assert captured["orchestration"]["actor_id"] == "trusted-user"
    assert captured["conversation"]["tenant_id"] == "trusted-tenant"
    assert captured["conversation"]["user_id"] == "trusted-user"
    assert captured["turn"]["tenant_id"] == "trusted-tenant"
    assert captured["turn"]["user_id"] == "trusted-user"
