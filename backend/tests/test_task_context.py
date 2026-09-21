from datetime import date

import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, Mock

from app.orchestration.schemas import AskKritonRequest, TaskContextSelection
from app.orchestration.task_context import ResolutionInput, resolve_task_context
from app.orchestration import service


IDENTITY = ResolutionInput(actor_id="user-1", tenant_id="tenant-1", role="Accountant")


def _request(**context) -> AskKritonRequest:
    return AskKritonRequest(
        query="Test professional task",
        task_context=TaskContextSelection(**context),
    )


def test_legacy_request_remains_compatible_and_uses_server_identity() -> None:
    decision = resolve_task_context(AskKritonRequest(query="What is depreciation?"), IDENTITY)

    assert decision.status == "complete"
    assert decision.resolved_context is not None
    assert decision.resolved_context.task_type == "general_question"
    assert decision.resolved_context.actor_id == "user-1"
    assert decision.resolved_context.tenant_id == "tenant-1"


def test_policy_research_lists_specific_missing_context() -> None:
    decision = resolve_task_context(_request(task_type="policy_research", jurisdiction="UK"), IDENTITY)

    assert decision.status == "clarification_required"
    assert decision.missing_fields == ["engagement_id", "framework", "period_end"]
    assert len(decision.clarification_questions) == 3


def test_supported_policy_context_is_normalized() -> None:
    decision = resolve_task_context(
        _request(
            task_type="policy_research", engagement_id="eng-1", jurisdiction="UK", framework="FRS 102",
            period_end=date(2026, 12, 31),
        ),
        IDENTITY,
        authorized_engagement_id="eng-1",
    )

    assert decision.status == "complete"
    assert decision.resolved_context is not None
    assert decision.resolved_context.jurisdiction == "GB"
    assert decision.resolved_context.framework == "UK_GAAP"


def test_unsupported_policy_context_fails_closed() -> None:
    decision = resolve_task_context(
        _request(
            task_type="policy_research", engagement_id="eng-1", jurisdiction="US", framework="US GAAP",
            period_end=date(2026, 12, 31),
        ),
        IDENTITY,
        authorized_engagement_id="eng-1",
    )

    assert decision.status == "unsupported"
    assert decision.reason_codes == ["UNSUPPORTED_JURISDICTION_FRAMEWORK"]


def test_reconciliation_requires_documents_period_and_currency() -> None:
    decision = resolve_task_context(_request(task_type="reconciliation"), IDENTITY)

    assert decision.status == "clarification_required"
    assert decision.missing_fields == ["engagement_id", "document_ids", "period_start", "period_end", "currency"]


def test_document_workflow_becomes_confidential() -> None:
    request = _request(task_type="document_evidence_extraction", engagement_id="eng-1")
    request.document_ids = ["doc-1"]
    decision = resolve_task_context(request, IDENTITY, authorized_engagement_id="eng-1")

    assert decision.status == "complete"
    assert decision.resolved_context is not None
    assert decision.resolved_context.data_classification == "CONFIDENTIAL"


def test_client_cannot_supply_trusted_identity_fields() -> None:
    with pytest.raises(ValidationError):
        AskKritonRequest.model_validate({
            "query": "test",
            "tenant_id": "forged-tenant",
            "actor_id": "forged-user",
        })


def test_engagement_selection_fails_closed_until_f1_authorization_exists() -> None:
    decision = resolve_task_context(
        _request(task_type="general_question", engagement_id="engagement-other"), IDENTITY
    )

    assert decision.status == "unsupported"
    assert decision.reason_codes == ["ENGAGEMENT_AUTHORIZATION_NOT_AVAILABLE"]


@pytest.mark.asyncio
async def test_incomplete_context_returns_before_safety_retrieval_or_providers(monkeypatch) -> None:
    for name in (
        "audit_query_received",
        "audit_request_validated",
        "audit_context_resolved",
        "audit_clarification_returned",
        "_finalise_and_return",
    ):
        monkeypatch.setattr(service, name, AsyncMock())
    prescreen = Mock(side_effect=AssertionError("prescreen must not run"))
    retrieval = AsyncMock(side_effect=AssertionError("retrieval must not run"))
    provider = AsyncMock(side_effect=AssertionError("provider must not run"))
    monkeypatch.setattr(service, "run_prescreen", prescreen)
    monkeypatch.setattr(service, "build_source_bundle", retrieval)
    monkeypatch.setattr(service, "classify_risk", provider)

    response = await service.ask_kriton(
        db=object(),
        sync_db=object(),
        actor_id="user-1",
        tenant_id="tenant-1",
        role="Accountant",
        request=_request(task_type="policy_research", jurisdiction="UK"),
    )

    assert response.outcome == "clarification_required"
    assert response.context_decision is not None
    assert response.context_decision.missing_fields == ["engagement_id", "framework", "period_end"]
    prescreen.assert_not_called()
    retrieval.assert_not_awaited()
    provider.assert_not_awaited()
