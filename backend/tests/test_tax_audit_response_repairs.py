from unittest.mock import AsyncMock

import pytest

from app.orchestration import claim_verification, review_mode, websearch
from app.orchestration.input_requirements import STATEMENT_ACTIONS, statement_not_question
from app.orchestration.research_parts import structured_research_parts
from app.orchestration.source_guarantee import official_sources_note
from app.orchestration.source_taxonomy import AUDIT, TAX, detect_topics
from app.orchestration.verification_service import verify_for_release, prune_rejected_claims
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — real pipeline with external boundaries stubbed


RISKS = """Global tax audits are rarely random. Authorities rely on financial patterns:
• Persistent Subsidiary Losses: Local entities showing multi-year losses while the parent remains profitable.
• Volatile Profit Margins: Sudden fluctuations without a commercial justification.
• High-Value Intercompany Transactions: Large shifts in management fees and royalties.
• Mismatched IP Ownership: Holding IP without corresponding local R&D personnel.
"""
TABLE = """Focus Area\tCore Audit Mechanism\tRisk Mitigation Strategy
Transfer Pricing\tEvaluates arm's length pricing.\tMaintain documentation.
Permanent Establishment (PE)\tAssesses taxable corporate presence.\tTrack footprints and authority.
Withholding Taxes (WHT)\tReviews cross-border payments.\tVerify treaty eligibility.
"""


def test_statement_actions_lead_to_real_requests_and_short_claim_review():
    assert statement_not_question(RISKS)
    for action in STATEMENT_ACTIONS:
        assert statement_not_question(f"{action} Context: {RISKS}") is None
    assert review_mode.is_review_request(f"{STATEMENT_ACTIONS[0]} Context: {RISKS}")
    assert not review_mode.is_review_request(f"{STATEMENT_ACTIONS[1]} Context: {RISKS}")
    assert not review_mode.is_review_request("Check if IFRS 18 replaces IAS 1")


async def test_statement_response_exposes_actions_through_the_real_pipeline(pipeline):
    from unittest.mock import MagicMock
    from app.orchestration import service
    from app.orchestration.schemas import AskKritonRequest
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=RISKS))
    assert response.outcome == "clarification_required"
    assert response.next_action.suggestions == STATEMENT_ACTIONS
    assert response.next_action.message not in response.next_action.suggestions


def test_text_transformations_do_not_become_new_tax_research_requests():
    from app.orchestration.pasted_material import review_instruction
    from app.orchestration.verification_service import requires_authoritative_evidence
    for action in STATEMENT_ACTIONS[1:]:
        query = f"{action} Context: {RISKS}"
        assert review_instruction(query) == action
        assert not requires_authoritative_evidence(review_instruction(query) or query)
    query = f"Explain the withholding tax requirements. Context: {RISKS}"
    assert requires_authoritative_evidence(review_instruction(query) or query)


@pytest.mark.parametrize("material,labels", [
    (RISKS, ["Persistent Subsidiary Losses", "Volatile Profit Margins", "High-Value Intercompany Transactions", "Mismatched IP Ownership"]),
    (TABLE, ["Transfer Pricing", "Permanent Establishment", "Withholding Taxes"]),
])
def test_retrieval_covers_every_structured_part_before_shortening(material, labels):
    parts = websearch.evidence_search_queries(material)
    assert len(parts) == len(labels)
    assert all(label in part for label, part in zip(labels, parts))
    assert websearch.sub_questions(material) == parts
    assert len(structured_research_parts(RISKS * 20)) <= 8


def test_markdown_table_header_and_separator_are_not_search_subjects():
    table = "| Focus | Mechanism |\n|---|---|\n| Transfer Pricing | Arm's length |\n| Permanent Establishment | Presence |"
    assert len(structured_research_parts(table)) == 2
    assert all("Focus Mechanism" not in part for part in structured_research_parts(table))


def test_tax_audits_route_to_tax_sources_and_mixed_audits_keep_both():
    query = "Prepare a response plan for a multi-jurisdictional tax audit under ASC 740."
    assert TAX in detect_topics(query) and AUDIT not in detect_topics(query)
    note = official_sources_note(query)
    assert "OECD" in note and "FASB" in note and "IAASB" not in note
    mixed = query + " Also assess financial-statement audit evidence under ISA 500."
    assert {TAX, AUDIT} <= detect_topics(mixed)
    assert "IAASB" in official_sources_note(mixed)
    assert "IAASB" in official_sources_note("Explain financial statement audit evidence under ISA 500")


async def test_empty_structured_search_is_retried_once_without_losing_other_sources(monkeypatch):
    from app.orchestration import official_evidence, official_standards
    monkeypatch.setattr(official_evidence, "official_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(official_standards, "official_standard_excerpts", AsyncMock(return_value=[]))
    calls = []

    async def search(query, **kwargs):
        calls.append(query)
        if "Permanent Establishment" in query and "official guidance" not in query:
            return []
        label = next(label for label in ["Transfer Pricing", "Permanent Establishment", "Withholding Taxes"] if label in query)
        return [WebSource(title=label, url=f"https://oecd.org/{label.replace(' ', '-')}", snippet=label)]

    monkeypatch.setattr(websearch, "web_search", search)
    results = await websearch.web_search_each(TABLE)
    assert len(results) == 3
    assert len(calls) == 4
    assert sum("official guidance" in query for query in calls) == 1


async def test_shared_official_page_keeps_passages_for_all_rows_without_mutating_cache(monkeypatch):
    from app.orchestration import official_evidence, official_standards
    monkeypatch.setattr(official_evidence, "official_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(official_standards, "official_standard_excerpts", AsyncMock(return_value=[]))
    cached = []

    async def search(query, **kwargs):
        source = WebSource(title="OECD guidance", url="https://oecd.org/guidance", snippet=query)
        cached.append(source)
        return [source]

    monkeypatch.setattr(websearch, "web_search", search)
    sources = await websearch.web_search_each(TABLE)
    assert len(sources) == 1
    assert all(label in sources[0].snippet for label in ["Transfer Pricing", "Permanent Establishment", "Withholding Taxes"])
    assert cached[0].snippet == websearch.evidence_search_queries(TABLE)[0]


@pytest.mark.parametrize("verdicts,expected", [
    ([review_mode.UNVERIFIED, review_mode.UNVERIFIED], "none"),
    ([review_mode.CORRECT, review_mode.UNVERIFIED], "partial"),
    ([review_mode.CORRECT, review_mode.INCORRECT], "complete"),
])
async def test_claim_review_completeness_reflects_verified_coverage(pipeline, verdicts, expected):
    from app.orchestration import service
    result = review_mode.ReviewResult(
        verdicts=[review_mode.ClaimVerdict(f"Claim {index}", verdict) for index, verdict in enumerate(verdicts)],
        sources=[], text="Claim-by-claim review.")
    response = await service._review_response(AsyncMock(), result, query_id="q", correlation_id="c", tenant_id="t",
                                              audit_chain_id="a", actor_id="u")
    assert response.answer.completeness == expected


async def test_labelled_operational_guidance_survives_but_accounting_rules_do_not():
    question = "Prepare an operational framework for a tax audit, including accounting requirements."
    answer = ("### General operational guidance\n"
              "Designate a response coordinator.\nCollect correspondence in a shared folder.\n"
              "### Accounting requirements\nASC 740 requires a provision for every tax audit.")
    result = await verify_for_release(answer, question=question, evidence=[], requires_authority=True)
    assert not result.passed and result.prunable
    assert len(result.general_explanations) == 2
    assert result.rejected_claims == ["ASC 740 requires a provision for every tax audit."]
    pruned = prune_rejected_claims(answer, result.rejected_claims)
    checked = await verify_for_release(pruned, question=question, evidence=[], requires_authority=True)
    assert checked.passed
    assert "Collect correspondence" in pruned and "ASC 740 requires" not in pruned


async def test_operational_guidance_is_retained_and_labelled_through_the_real_pipeline(pipeline):
    from app.domains.model_gateway.agent import AgentOutcome
    pipeline.answers(AgentOutcome(text="### General operational guidance\nDesignate a response coordinator.\nCollect correspondence in a shared folder."))
    response, _ = await pipeline.ask("Prepare an operational framework for handling a tax audit.")
    assert response.answer is not None and "Designate a response coordinator" in response.answer.text
    assert response.answer.completeness != "none"
    assert any("general explanation" in note.lower() for note in response.answer.limitations)


async def test_identical_words_inside_a_rule_are_still_checked():
    result = await verify_for_release(
        "### General operational guidance\nMaintain correspondence.\n"
        "ASC 740 requires this step: Maintain correspondence.",
        question="Prepare an operational framework for a tax audit.", evidence=[], requires_authority=True)
    assert not result.passed
    assert result.rejected_claims == ["ASC 740 requires this step: Maintain correspondence."]


@pytest.mark.parametrize("claim", [
    "Maintain records for 7 years.", "Consider recognising a tax provision under ASC 740.",
    "Review the mandatory withholding tax rate of 15%.", "Collect documents required by law.",
])
async def test_guidance_heading_never_exempts_specific_requirements(claim):
    result = await verify_for_release("### General operational guidance\n" + claim,
                                     question="Prepare an operational framework for a tax audit.",
                                     evidence=[], requires_authority=True)
    assert not result.passed and not result.general_explanations


async def test_claim_review_reports_missing_evidence_separately_from_verifier_failure(monkeypatch):
    monkeypatch.setattr(claim_verification, "verify_claims", AsyncMock(return_value=claim_verification.VerificationResult()))
    results = await review_mode._judge_each(["Claim with no sources", "Claim with evidence"], [[], ["[REF-1] evidence"]])
    assert results[0].reason == "No relevant source was retrieved."
    assert results[1].reason == "Evidence verification could not complete."
    assert all(result.verdict == review_mode.UNVERIFIED for result in results)


async def test_review_retries_semantic_gaps_without_researching_supported_claims(monkeypatch):
    claims = ["Transfer pricing is reviewed on an arm's length basis.", "Recurring subsidiary losses can prompt scrutiny."]
    monkeypatch.setattr(review_mode, "extract_review_claims", AsyncMock(return_value=claims))
    monkeypatch.setattr(review_mode, "_official_excerpts", AsyncMock(return_value=[]))
    calls = []

    async def search(query, **kwargs):
        calls.append(query)
        supported = query == claims[0] or query.endswith("official guidance")
        return [WebSource(title="Official guidance", url="https://oecd.org/" + ("supported" if supported else "unrelated"),
                          snippet="Evidence supports this claim." if supported else "Evidence on a different subject.")]

    async def judge(items, evidence, question=""):
        if "Evidence supports" not in " ".join(evidence):
            return claim_verification.VerificationResult(checked=1, ran=True, rejected_ids=[1])
        import re
        supporting = next(item for item in evidence if "Evidence supports" in item)
        ref = re.search(r"\[(REF-\d+)\]", supporting).group(1)
        return claim_verification.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1: [ref]})

    monkeypatch.setattr(review_mode, "web_search", search)
    monkeypatch.setattr(claim_verification, "verify_claims", judge)
    result = await review_mode.review_pasted_text(RISKS)
    assert [verdict.verdict for verdict in result.verdicts] == [review_mode.CORRECT, review_mode.CORRECT]
    assert len(calls) == 3 and calls.count(claims[0]) == 1
    assert not any(source.url.endswith("unrelated") for source in result.sources)


async def test_review_does_not_research_again_when_the_verifier_is_unavailable(monkeypatch):
    claims = ["A claim about transfer pricing."]
    monkeypatch.setattr(review_mode, "extract_review_claims", AsyncMock(return_value=claims))
    monkeypatch.setattr(review_mode, "_official_excerpts", AsyncMock(return_value=[]))
    search = AsyncMock(return_value=[WebSource(title="Guidance", url="https://oecd.org/guide", snippet="Some evidence.")])
    monkeypatch.setattr(review_mode, "web_search", search)
    monkeypatch.setattr(claim_verification, "verify_claims", AsyncMock(return_value=claim_verification.VerificationResult()))
    result = await review_mode.review_pasted_text(RISKS)
    assert search.await_count == 1
    assert "Evidence verification could not complete" in result.text
    assert "has not been established as false" in result.text
