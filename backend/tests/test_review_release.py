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
    # The reported case: a question about the user's own figures, rated HIGH.
    # Pinned so the test never calls the live risk classifier (CI has no key).
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="HIGH"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
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


# ── A disproved figure is removed, not shown with a warning (22 Oct 2026) ──

from app.orchestration.review_release import remove_disproved_figures  # noqa: E402

_MISMATCH = "Calculation mismatch: 780,000 ÷ 0.55 equals 1418181.82, not 1560000."
_ANSWER = ("Required revenue = £780,000 ÷ 0.55 = £1,560,000.00.\n"
           "Current revenue is £2,400,000 and profit is £540,000.")


def test_only_the_disproved_statement_is_removed_and_the_verified_result_is_named():
    cleaned, notes = remove_disproved_figures(_ANSWER, [_MISMATCH])
    assert "£1,560,000" not in cleaned
    assert "£2,400,000" in cleaned and "£540,000" in cleaned
    assert notes == ["£1,560,000.00 (780,000 ÷ 0.55 equals 1418181.82)"]


def test_an_unverifiable_figure_is_left_for_the_warning():
    failures = ["unreconciled_figures: £9,999", "Grounding check failed: no citation"]
    assert remove_disproved_figures(_ANSWER, failures) == (_ANSWER, [])


def test_the_warning_says_the_figure_was_removed_not_that_it_could_not_be_checked():
    removed = release_warning([_MISMATCH], disproved_removed=True)
    assert "did not match its own calculation was removed" in removed and "re-checked" not in removed
    assert "could not be re-checked" in release_warning([_MISMATCH])


@pytest.mark.parametrize("reply", [
    "Required revenue = £780,000 ÷ 0.55 = £1,560,000.00.",
    "## Forecast\nRequired revenue = £780,000 ÷ 0.55 = £1,560,000.00.",
])
def test_a_reply_that_is_only_the_disproved_statement_leaves_nothing_to_release(reply):
    # Empty text sends the answer to review instead of releasing a heading.
    assert remove_disproved_figures(reply, [_MISMATCH]) == ("", ["£1,560,000.00 (780,000 ÷ 0.55 equals 1418181.82)"])
