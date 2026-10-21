"""The reader always gets the answer (product decision, 2026-10-21).

An answer that fails a check is shown with a plain warning naming what could
not be verified, and still goes to Review Tasks; it is no longer replaced by
"Response validation failed; escalated for review". Runs through the real
ask_kriton pipeline with only persistence, retrieval and the model replaced.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import learned_answers, review, service
from app.orchestration.review_release import release_warning
from app.orchestration.schemas import AskKritonRequest, ValidationResult

ANSWER = "**Journal entry for the year’s depreciation**\n\n- Debit Depreciation Expense 137,085\n- Credit Accumulated Depreciation 137,085"


@pytest.fixture
def pipeline(monkeypatch):
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", AsyncMock(return_value=AgentOutcome(text=ANSWER)))
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=""))
    review_case = AsyncMock(return_value=SimpleNamespace(id="rc-1"))
    monkeypatch.setattr(service, "create_review_case", review_case)
    # Every check fails the way the reported answers did.
    monkeypatch.setattr(service, "validate_answer", lambda *a, **k: ValidationResult(
        passed=False, degraded_route="HUMAN_REVIEW",
        failures=["Grounding check failed: answer contains substantive content but no eligible sources exist "
                  "in the SourceBundle and no live retrieval sources were supplied."]))
    return SimpleNamespace(review_case=review_case)


async def test_a_failed_check_shows_the_answer_with_a_warning_and_still_notifies_a_reviewer(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Prepare the journal entry for this year's depreciation."))
    assert response.outcome != "escalated"
    assert response.answer is not None and "137,085" in response.answer.text
    assert response.answer.limitations[0].startswith("Not fully verified: no source was found to confirm it")
    assert not (response.next_action and "escalated for review" in (response.next_action.message or ""))
    pipeline.review_case.assert_awaited_once()


def test_the_warning_names_what_could_not_be_verified():
    assert "these figures could not be matched to the sources: 658,000" in release_warning(["unreconciled_figures: 658,000"])
    assert "some statements could not be confirmed" in release_warning(['Rejected: "| Depreciation | [Amount] |"'])
    assert "did not pass every automatic check" in release_warning(["Something new"])
    assert release_warning(["Grounding check failed: x", "Required authoritative evidence is unavailable"]).count(
        "no source was found") == 1
