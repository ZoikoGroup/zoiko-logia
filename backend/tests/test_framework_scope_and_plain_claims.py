from unittest.mock import AsyncMock

import pytest

from app.orchestration.review_mode import is_review_request
from app.orchestration.framework_scope import foreign_framework_statements, FRAMEWORK_GAP
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


CLAIMS = """Check each claim separately and cite relevant authoritative evidence:
• Persistent subsidiary losses can attract transfer-pricing scrutiny.
• Legal ownership alone always entitles an entity to all intellectual-property returns.
• Large royalty payments automatically prove tax avoidance.
"""


@pytest.mark.parametrize("instruction", [
    "Check each claim separately", "Verify every statement", "Assess each claim", "Review each statement",
])
def test_explicit_review_of_plain_bullets_does_not_need_labels_or_a_size_threshold(instruction):
    assert is_review_request(instruction + ":\n• First factual assertion.\n• Second factual assertion.")
    assert is_review_request(CLAIMS)
    assert not is_review_request("Prepare a checklist:\n• Review the contract.\n• Collect correspondence.")


@pytest.mark.parametrize("question,answer", [
    ("Explain recognition under ASC 740", "IAS 37 requires recognition when an outflow is probable."),
    ("Explain IFRS requirements", "ASC 740 provides the recognition conditions."),
    ("Apply UK GAAP FRS 102", "IAS 37 requires a provision in these circumstances."),
    ("Apply Ind AS 37", "ASC 450 establishes the conditions."),
])
def test_supported_foreign_framework_rules_still_do_not_answer_the_requested_framework(question, answer):
    assert foreign_framework_statements(question, answer)


def test_comparisons_and_honest_evidence_gaps_keep_their_scope():
    assert not foreign_framework_statements("Compare ASC 740 with IAS 37", "IAS 37 requires a present obligation.")
    assert not foreign_framework_statements("Explain ASC 740", "The retrieved evidence does not establish IAS 37 applicability.")
    assert not foreign_framework_statements("Explain IFRS 16", "IFRS 16 addresses leases.")


def test_unqualified_rules_cannot_hide_their_foreign_source_framework():
    from types import SimpleNamespace
    source = SimpleNamespace(ref_id="REF-1", title="IAS 37 Provisions", framework="IFRS", evidence_preview="")
    assert foreign_framework_statements("Explain ASC 740", "Recognition requires a probable outflow. [REF-1]", [source])


async def test_document_suggestions_under_nested_topics_retain_the_guidance_classification():
    from app.orchestration.verification_service import verify_for_release
    text = ("### General operational guidance\n#### Leases\nCollect contracts and payment schedules.\n"
            "#### Impairment\nCompile forecasts and supporting estimates.\n"
            "### Requirements\nThe retrieved evidence does not establish the requirements.")
    result = await verify_for_release(text, question="Compare the documentation typically needed under IFRS.",
                                      evidence=[], requires_authority=True)
    assert result.passed and len(result.general_explanations) == 2


async def test_plain_claim_check_reaches_the_review_pipeline(pipeline, monkeypatch):
    from app.orchestration import service
    from app.orchestration.review_mode import ReviewResult, ClaimVerdict, UNVERIFIED
    review = AsyncMock(return_value=ReviewResult(
        verdicts=[ClaimVerdict("A claim", UNVERIFIED)], sources=[], text="I checked 1 factual claims in the text: 0 correct, 0 incorrect, 1 could not be verified."))
    monkeypatch.setattr(service, "review_pasted_text", review)
    response, _ = await pipeline.ask(CLAIMS)
    review.assert_awaited_once()
    assert response.answer.prompt_id == "claim-review-v1"
    pipeline.agent.assert_not_awaited()


async def test_wrong_framework_cannot_be_released_with_only_a_warning(pipeline, monkeypatch):
    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    from app.orchestration.verification_service import AnswerVerification
    from app.orchestration.schemas import ValidationResult
    # Reproduce the dangerous case: the claim judge accepts a correctly
    # sourced foreign rule. The final scope boundary must still reject it.
    monkeypatch.setattr(service, "verify_for_release", AsyncMock(return_value=AnswerVerification(True)))
    monkeypatch.setattr(service, "validate_answer", lambda *args, **kwargs: ValidationResult(passed=True))
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="LOW"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=None))
    draft = "### Applicable conditions\nIAS 37 requires recognition when a present obligation, probable outflow and reliable estimate exist."
    pipeline.answers(AgentOutcome(text=draft))
    pipeline.rewrite.return_value = draft
    response, _ = await pipeline.ask("Is every tax audit immediately recognised as a provision under ASC 740? Explain the conditions.")
    assert response.answer is not None, (response.outcome, response.next_action, pipeline.agent.await_count, pipeline.rewrite.await_count)
    assert response.answer.text == FRAMEWORK_GAP
    assert response.answer.completeness == "none"
    assert response.answer.citations == []
    assert "IAS 37 requires" not in response.answer.text
    assert response.chart_offer is None
