"""answer_statements_removed: which statements verification removed, at
which stage, and why — through the complete ask_kriton pipeline.

The two partial IFRS 15 runs of 2026-10-16 (qry-5b9439b95cd3,
qry-73c1dfc01cb7) lost statements to release pruning and nothing recorded
which. A statement the cited evidence does not address is not thereby false:
the reason codes keep "not_in_cited_evidence" apart from
"contradicted_by_cited_source"."""
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import claim_verification, service
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import WITHHELD_QUESTION, pipeline  # noqa: F401 — full-pipeline fixture
from tests.test_ifrs15_release_stability import CLAIMS, QUESTION, STANDARD_EXCERPT, SUPPORT

OFFICIAL = WebSource(title="IFRS 15 — official text (IFRS Foundation)", provider="IFRS Foundation",
                     url="https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2026/issued/ifrs15.html",
                     snippet=STANDARD_EXCERPT)
UNCITED = "Ask the company's auditor how to treat the £120,000 before the year end."
WITH_EMAIL = "Send the £120,000 contract to jane.doe@example.com for a ruling on day one [REF-1]."


@pytest.fixture
def verifier(monkeypatch):
    """A faithful verifier: supported only when the supporting sentence is in
    the evidence shown; statements listed in `contradict` are contradicted."""
    state = SimpleNamespace(contradict=set())

    async def complete_auxiliary(*, purpose, user, **_):
        evidence = " ".join(user.split("EVIDENCE:\n", 1)[1].split("\n\nCLAIMS:\n", 1)[0].split())
        results = []
        for number, claim in re.findall(r"^(\d+)\. (.*)$", user.split("\n\nCLAIMS:\n", 1)[1], re.M):
            key = next((k for k, text in CLAIMS.items() if text.split(" [REF")[0] in claim), None)
            if key in state.contradict:
                results.append({"claim": int(number), "verdict": "contradicted", "references": [],
                                "evidence_says": "Revenue is recognised as the service is provided."})
                continue
            supported = bool(key) and bool(SUPPORT.get(key)) and SUPPORT[key] in evidence
            results.append({"claim": int(number), "verdict": "supported" if supported else "not_in_evidence",
                            "references": ["REF-1"] if supported else [], "evidence_says": ""})
        return SimpleNamespace(text=json.dumps({"results": results}))

    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(claim_verification, "gateway", SimpleNamespace(
        may_use=lambda *args, **kwargs: True, complete_auxiliary=complete_auxiliary))
    return state


@pytest.fixture
def ask(pipeline, verifier):
    async def run(text: str, sources=(OFFICIAL,), question=QUESTION, **outcome):
        pipeline.answers(AgentOutcome(text=text, sources=list(sources), **outcome))
        response, audited = await pipeline.ask(question)
        event = service.audit_answer_statements_removed   # replaced by an AsyncMock in the fixture
        payload = event.await_args.kwargs if event.await_args else None
        return response, audited, payload

    return run


def entries(payload, stage):
    return next(item for item in payload["stages"] if item["stage"] == stage)["removed"]


async def test_nothing_removed_writes_no_event(ask):
    response, _, payload = await ask("\n".join([CLAIMS["contract liability"], CLAIMS["over time"]]))
    assert payload is None and response.answer.completeness == "complete"


async def test_a_pruned_unsupported_statement_is_recorded_as_not_in_evidence_not_as_false(ask):
    response, audited, payload = await ask("\n".join([CLAIMS["contract liability"], CLAIMS["over time"],
                                                     CLAIMS["on day one"]]))
    [removed] = entries(payload, "release_prune")
    assert removed["reason_code"] == "not_in_cited_evidence"
    assert removed["excerpt"] == "The full £120,000 is recognised as revenue on day one."
    assert re.fullmatch(r"[0-9a-f]{32}", removed["statement_hash"])
    assert removed["cited_refs"] == ["REF-1"] and removed["source_ids"]
    # One record of the outcome everywhere.
    assert payload["completeness"] == audited.completeness == response.answer.completeness == "partial"
    assert payload["outcome"] == audited.outcome == "answered"
    stage = payload["stages"][0]
    assert stage["answer_hash_before"] != stage["answer_hash_after"] and stage["removed_count"] == 1


async def test_a_contradicted_statement_is_recorded_as_contradicted(ask, verifier):
    verifier.contradict = {"on day one"}
    _, _, payload = await ask("\n".join([CLAIMS["contract liability"], CLAIMS["over time"], CLAIMS["on day one"]]))
    [removed] = entries(payload, "release_prune")
    assert removed["reason_code"] == "contradicted_by_cited_source"


async def test_an_uncited_statement_is_recorded_as_missing_citation(ask):
    _, _, payload = await ask("\n".join([CLAIMS["contract liability"], CLAIMS["over time"], UNCITED]))
    [removed] = entries(payload, "release_prune")
    assert removed["reason_code"] == "missing_citation" and removed["cited_refs"] == []


async def test_a_withheld_answer_records_every_statement_and_none(ask):
    response, audited, payload = await ask(CLAIMS["on day one"])
    removed = entries(payload, "release_withheld")
    assert [item["reason_code"] for item in removed] == ["not_in_cited_evidence"]
    assert payload["completeness"] == audited.completeness == "none"


async def test_withheld_figures_are_recorded(ask):
    _, audited, payload = await ask("Verified working only.", sources=(), question=WITHHELD_QUESTION,
                                    unreconciled_figures=["£9,999", "13.4%"])
    removed = entries(payload, "figure_reconciliation")
    assert [(item["excerpt"], item["reason_code"]) for item in removed] == [
        ("£9,999", "figure_unreconciled"), ("13.4%", "figure_unreconciled")]
    assert payload["completeness"] == audited.completeness == "partial"


async def test_the_excerpt_is_redacted(ask):
    _, _, payload = await ask("\n".join([CLAIMS["contract liability"], CLAIMS["over time"], WITH_EMAIL]))
    [removed] = entries(payload, "release_prune")
    assert "jane.doe@example.com" not in removed["excerpt"] and "[REDACTED_EMAIL" in removed["excerpt"]


def test_a_stage_is_bounded_and_codes_are_known():
    many = [(f"Statement number {n} about the £120,000 contract [REF-1].", "not_in_cited_evidence", {}) for n in range(25)]
    stage = service.removal_stage("release_prune", "before", "after", many,
                                  [SimpleNamespace(ref_id="REF-1", source_id="src-1")])
    assert stage["removed_count"] == 25 and len(stage["removed"]) == 20
    assert stage["removed"][0]["source_ids"] == ["src-1"]
    long = service.removal_stage("release_prune", "b", "a", [("x " * 200, "made_up_code", {})], [])
    assert long["removed"][0]["reason_code"] == "unspecified"
    assert long["removed"][0]["excerpt"].endswith("…") and len(long["removed"][0]["excerpt"]) == 121


async def test_contradiction_removal_reports_what_it_removed(monkeypatch):
    # The earlier check for non-authoritative answers: a statement contradicted
    # on the recheck and on a confirming check is removed, and reported.
    from app.orchestration import verification_service
    from app.orchestration.claim_verification import Contradiction, VerificationResult
    wrong = "The VAT registration threshold is £85,000 from 2024."
    verdict = VerificationResult(checked=1, ran=True, contradicted=[Contradiction(wrong, "£90,000")],
                                 rejected_ids=[1], contradicted_ids=[1])
    monkeypatch.setattr(claim_verification, "enabled", lambda: True)
    monkeypatch.setattr(claim_verification, "verify_claims", AsyncMock(return_value=verdict))
    monkeypatch.setattr(verification_service.model_gateway_service, "run_grounded_completion",
                        AsyncMock(return_value=wrong + "\nRegister within 30 days."))
    metrics = SimpleNamespace(run=lambda name, awaitable: awaitable)
    removed: list[dict] = []
    text, note = await verification_service._verify_answer_claims(
        wrong, evidence=["[REF-1] The threshold is £90,000."], question="What is the UK VAT threshold?",
        grounded_input="", report=AsyncMock(), metrics=metrics, removed=removed)
    assert wrong not in text and note == verification_service._CLAIM_REMOVED_NOTE
    assert removed == [{"statement": wrong, "reason_code": "contradicted_by_cited_source", "confirmations": 2}]
