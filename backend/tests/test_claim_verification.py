"""Claim verification: specific statements in an answer are judged against
the evidence it was composed from (app/orchestration/claim_verification.py)."""
import json
from types import SimpleNamespace

import pytest

from app.orchestration import claim_verification as cv

# The held-out failure that motivated this: £1.35m is in the evidence, but as
# the threshold for JOINING the scheme, not leaving it.
ANSWER = (
    "A business must stop using the VAT Cash Accounting Scheme when it is no longer eligible.\n"
    "If the business's VAT-taxable turnover exceeds £1.35 million, it must leave the scheme. "
    "You can join if your estimated turnover is £1.35 million or less.\n"
    "```chart\n{\"data\": [1, 2, 3]}\n```"
)
EVIDENCE = [
    "VAT Cash Accounting Scheme — You can use cash accounting if your estimated VAT taxable turnover "
    "during the next tax year is not more than £1.35 million. You must leave the scheme if your VAT "
    "taxable turnover is more than £1.6 million.",
]


def test_only_statements_with_a_checkable_specific_are_extracted():
    claims = cv.extract_claims(ANSWER)
    assert claims == [
        "If the business's VAT-taxable turnover exceeds £1.35 million, it must leave the scheme.",
        "You can join if your estimated turnover is £1.35 million or less.",
    ]  # the general opening sentence and the chart fence are not claims


def test_table_rows_are_claims():
    table = "| Scheme | Leave above |\n| --- | --- |\n| Flat Rate Scheme | £230,000 |"
    assert cv.extract_claims(table) == ["| Flat Rate Scheme | £230,000 |"]


def _fake_groq(monkeypatch, payload, calls):
    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    class _Client:
        def __init__(self, *a, **kw):
            self.chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr(cv, "AsyncGroq", _Client)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")


async def test_contradicted_claim_is_reported_with_what_the_evidence_says(monkeypatch):
    calls = []
    _fake_groq(monkeypatch, {"results": [
        {"claim": 1, "verdict": "contradicted", "evidence_says": "You must leave the scheme if turnover is more than £1.6 million."},
        {"claim": 2, "verdict": "supported", "evidence_says": ""},
    ]}, calls)
    result = await cv.verify_claims(cv.extract_claims(ANSWER), EVIDENCE, "When must I leave cash accounting?")
    assert result.ran and result.checked == 2 and result.supported == 1
    assert [c.claim for c in result.contradicted] == [cv.extract_claims(ANSWER)[0]]
    assert "£1.6 million" in result.contradicted[0].evidence_says
    # The verifier judges each claim as used in the answer to the question.
    sent = calls[0]["messages"][1]["content"]
    assert "[E1]" in sent and "1. If the business" in sent
    assert "QUESTION:\nWhen must I leave cash accounting?" in sent


@pytest.mark.parametrize("payload", [{"results": "not a list"}, {"unexpected": 1}, {"results": [{"claim": 99, "verdict": "contradicted"}]}])
async def test_an_unreadable_verdict_is_unverified(monkeypatch, payload):
    _fake_groq(monkeypatch, payload, [])
    result = await cv.verify_claims(cv.extract_claims(ANSWER), EVIDENCE)
    assert result.contradicted == [] and not result.ran


async def test_verification_is_skipped_without_evidence_key_or_when_disabled(monkeypatch):
    calls = []
    _fake_groq(monkeypatch, {"results": []}, calls)
    assert not (await cv.verify_claims(cv.extract_claims(ANSWER), [])).ran
    monkeypatch.setenv("CLAIM_VERIFICATION", "off")
    assert not (await cv.verify_claims(cv.extract_claims(ANSWER), EVIDENCE)).ran
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.delenv("GROQ_API_KEY")
    assert not (await cv.verify_claims(cv.extract_claims(ANSWER), EVIDENCE)).ran
    assert calls == []


async def test_a_model_failure_never_blocks_the_answer(monkeypatch):
    class _Broken:
        def __init__(self, *a, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr(cv, "AsyncGroq", _Broken)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    assert not (await cv.verify_claims(cv.extract_claims(ANSWER), EVIDENCE)).ran


def test_correction_request_quotes_both_sides():
    request = cv.correction_request(ANSWER, [cv.Contradiction("exceeds £1.35 million", "more than £1.6 million")])
    assert "Your answer says: \"exceeds £1.35 million\"" in request
    assert "The cited evidence says: \"more than £1.6 million\"" in request


def test_a_statement_that_still_contradicts_is_removed():
    claim = cv.extract_claims(ANSWER)[0]
    cleaned = cv.remove_claims(ANSWER, [claim])
    assert claim not in cleaned
    assert "You can join if your estimated turnover is £1.35 million or less." in cleaned


async def test_an_answer_whose_figures_are_not_in_the_evidence_is_mostly_unconfirmed(monkeypatch):
    # India FY 2025-26 slabs answered with the FY 2024-25 table from memory.
    _fake_groq(monkeypatch, {"results": [
        {"claim": 1, "verdict": "not_in_evidence"}, {"claim": 2, "verdict": "not_in_evidence"},
        {"claim": 3, "verdict": "supported"},
    ]}, [])
    claims = ["Up to ₹3,00,000 is nil.", "₹3,00,001 to ₹7,00,000 is 5%.", "Rates apply from FY 2025-26 under 115BAC."]
    result = await cv.verify_claims(claims, ["Income tax return forms for individuals."], "India income tax slabs FY 2025-26?")
    assert result.mostly_unconfirmed and not result.contradicted


def test_one_unconfirmed_figure_is_not_enough_to_flag():
    assert not cv.VerificationResult(checked=1, not_in_evidence=1, ran=True).mostly_unconfirmed
    assert not cv.VerificationResult(checked=4, not_in_evidence=1, supported=3, ran=True).mostly_unconfirmed
    assert not cv.VerificationResult(checked=4, not_in_evidence=4, ran=False).mostly_unconfirmed


# ── service._verify_answer_claims: the four outcomes ─────────────────────────

from unittest.mock import AsyncMock  # noqa: E402

from app.orchestration import service  # noqa: E402
from app.orchestration.telemetry import StageMetrics  # noqa: E402


def _verdicts(monkeypatch, *results):
    queue = list(results)

    async def fake_verify(claims, evidence, question=""):
        return queue.pop(0)

    monkeypatch.setattr(cv, "verify_claims", fake_verify)
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")


async def _run(answer="Turnover over £1.35 million means you must leave.", question="When must I leave?"):
    return await service._verify_answer_claims(
        answer, evidence=["You must leave if turnover is more than £1.6 million."], question=question,
        grounded_input="INPUT", report=AsyncMock(), metrics=StageMetrics(),
    )


async def test_a_contradiction_is_corrected_by_one_rewrite(monkeypatch):
    claim = "Turnover over £1.35 million means you must leave."
    _verdicts(monkeypatch, cv.VerificationResult(checked=1, contradicted=[cv.Contradiction(claim, "£1.6 million")], ran=True),
              cv.VerificationResult(checked=1, supported=1, ran=True))
    rewrite = AsyncMock(return_value="You must leave when turnover is more than £1.6 million.")
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", rewrite)
    answer, note = await _run()
    assert answer == "You must leave when turnover is more than £1.6 million." and note is None
    assert "£1.6 million" in rewrite.await_args.args[0]  # the conflict is spelled out for the rewrite


async def test_a_contradiction_that_survives_the_rewrite_is_removed(monkeypatch):
    claim = "Leave at £1.35 million."
    # Initial verdict, post-rewrite recheck, and the confirming check before removal.
    _verdicts(monkeypatch, cv.VerificationResult(checked=1, contradicted=[cv.Contradiction(claim, "£1.6m")], ran=True),
              cv.VerificationResult(checked=1, contradicted=[cv.Contradiction(claim, "£1.6m")], ran=True),
              cv.VerificationResult(checked=1, contradicted=[cv.Contradiction(claim, "£1.6m")], ran=True))
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion",
                        AsyncMock(return_value="Cash accounting.\nLeave at £1.35 million."))
    answer, note = await _run()
    assert "£1.35 million" not in answer and note == service._CLAIM_REMOVED_NOTE


async def test_unconfirmed_figures_for_a_current_rate_question_are_flagged(monkeypatch):
    _verdicts(monkeypatch, cv.VerificationResult(checked=3, not_in_evidence=3, ran=True))
    answer, note = await _run("Up to ₹3,00,000 is nil. ₹3,00,001-₹7,00,000 is 5%. Above that 10%.",
                              question="What are the current income tax slabs in India?")
    assert note == service._CLAIMS_UNCONFIRMED_NOTE and answer.startswith("Up to ₹3,00,000")


async def test_a_supported_answer_is_left_alone(monkeypatch):
    _verdicts(monkeypatch, cv.VerificationResult(checked=1, supported=1, ran=True))
    assert await _run() == ("Turnover over £1.35 million means you must leave.", None)

@pytest.mark.parametrize("results", [
    [{"claim": 0, "verdict": "supported"}],
    [{"claim": -1, "verdict": "supported"}],
    [{"claim": True, "verdict": "supported"}],
    [{"claim": 1, "verdict": "unknown"}],
    [{"claim": 1, "verdict": "supported"}, {"claim": 1, "verdict": "supported"}],
])
async def test_invalid_and_duplicate_claim_ids_cannot_pass(monkeypatch, results):
    _fake_groq(monkeypatch, {"results": results}, [])
    verdict = await cv.verify_claims(["VAT rate is 20%."] * len(results), EVIDENCE)
    assert not verdict.ran and not verdict.passed


async def test_verifier_redacts_all_external_inputs(monkeypatch):
    calls = []
    _fake_groq(monkeypatch, {'results': [{'claim': 1, 'verdict': 'supported', 'references': ['REF-1']}]}, calls)
    await cv.verify_claims(['Contact alice@example.com for the rate.'], ['[REF-1] bob@example.com publishes it.'], 'Email charlie@example.com?')
    content = calls[0]['messages'][1]['content']
    assert all(address not in content for address in ('alice@example.com', 'bob@example.com', 'charlie@example.com'))
