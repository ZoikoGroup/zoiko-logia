"""A failed release verification logs which statements were rejected and
why (3 Nov 2026): the answer receipt keeps only the final "The sources
provided do not establish an answer to this.", so a UK employer NI failure
could not be traced to the statement that failed. Logging only."""
import json
import logging
from unittest.mock import AsyncMock

from tests.test_answer_status_pipeline import pipeline  # noqa: F401


async def test_rejected_statements_are_logged(pipeline, monkeypatch, caplog):
    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    from app.orchestration.schemas import ValidationResult
    from app.orchestration.verification_service import AnswerVerification
    claim = "The employer rate is 15% on all earnings."
    monkeypatch.setattr(service, "verify_for_release", AsyncMock(return_value=AnswerVerification(
        False, failures=["claim_not_in_evidence"], rejected_claims=[claim], rejected_reasons=["not_in_evidence"])))
    monkeypatch.setattr(service, "validate_answer", lambda *args, **kwargs: ValidationResult(passed=True))
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="LOW"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=None))
    pipeline.answers(AgentOutcome(text=claim))
    pipeline.rewrite.return_value = claim
    with caplog.at_level(logging.INFO, logger="kriton.requests"):
        response, _ = await pipeline.ask("What is the current UK employer National Insurance contribution rate?")
    # On kriton.requests: the only logger app/main.py writes to kriton-requests.log.
    records = [r.getMessage() for r in caplog.records
               if r.name == "kriton.requests" and r.getMessage().startswith("Release verification failed")]
    assert records, [r.getMessage()[:80] for r in caplog.records]
    logged = json.loads(records[-1].split(" ", 4)[-1])
    assert logged["rejected"][0] == {"claim": claim, "reason": "not_in_evidence"}
    assert "claim_not_in_evidence" in logged["failures"]
    # The answer itself is decided exactly as before.
    assert claim not in (response.answer.text if response.answer else "")
