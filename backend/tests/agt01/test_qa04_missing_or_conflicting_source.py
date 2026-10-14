"""QA 4 — missing or conflicting source: disclose, clarify or escalate; no invented authority."""
from agt01_support import reply, run

from app.orchestration.verification_service import AnswerVerification, decide_release_failure


async def test_an_answer_with_no_source_for_its_figure_is_withheld():
    outcome, _, _ = await run([reply("The 2023 threshold was £85,000."), reply("The 2023 threshold was £85,000.")],
                              question="What was the UK VAT registration threshold in 2023?")
    assert outcome.unreconciled_figures == ["£85,000"] and "withheld" in outcome.text


def test_an_unverifiable_answer_becomes_an_evidence_gap_or_review():
    failed = AnswerVerification(passed=False, failures=["no_supporting_source"])
    low = decide_release_failure("Rule X applies.", failed, risk_level="LOW", validation_passed=True)
    assert not low.escalate and "do not establish" in low.text
    high = decide_release_failure("Rule X applies.", failed, risk_level="HIGH", validation_passed=True)
    assert high.escalate
