"""Shared contracts, exercised across domains rather than exact question wording."""
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.domains.model_gateway import auxiliary as gateway
from app.orchestration import evidence_planning, review_mode, claim_verification, coverage_review, websearch
from app.orchestration.chart_offer import offer_chart
from app.orchestration.input_requirements import statement_not_question
from app.orchestration.verification_service import operational_guidance_claims, verify_for_release
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


def subject(name, *, claim_id=None, query=None):
    return dict(subject=name, query=query or name, alternative=name + " qualifications and exceptions", claim_id=claim_id)


@pytest.fixture
def planner(monkeypatch):
    monkeypatch.setenv("EVIDENCE_PLANNING", "on")
    monkeypatch.setattr(gateway, "may_use", lambda *args: True)
    complete = AsyncMock()
    monkeypatch.setattr(gateway, "complete_auxiliary", complete)
    return complete


@pytest.mark.parametrize("question,parts", [
    ("Contrast transfer pricing, permanent establishment and withholding taxes, covering purpose and preparation.",
     ["Transfer pricing audit", "Permanent establishment audit", "Withholding tax audit"]),
    ("Explain leases, impairment and provisions under IFRS, with documentation for each.",
     ["IFRS lease documentation", "IFRS impairment documentation", "IFRS provisions documentation"]),
    ("Compare audit sampling and analytical procedures, including limitations of each.",
     ["Audit sampling limitations", "Analytical procedures limitations"]),
])
async def test_prose_subjects_get_separate_research_without_question_specific_regex(planner, question, parts):
    planner.return_value = SimpleNamespace(text=json.dumps({"subjects": [subject(part) for part in parts]}))
    plan = await evidence_planning.plan_evidence_search(question, [question])
    assert plan.method == "semantic"
    assert [item.subject for item in plan.subjects] == parts
    assert planner.await_args.kwargs["purpose"] == "query_classification"


async def test_contextual_claim_plan_preserves_identity_order_and_does_not_search_the_assumed_conclusion(planner):
    claims = ["Persistent subsidiary losses can attract scrutiny.", "Legal ownership always entitles an entity to all IP returns."]
    planner.return_value = SimpleNamespace(text=json.dumps({"subjects": [
        subject("IP economic returns", claim_id=2, query="Transfer pricing intangible ownership functions risks returns"),
        subject("Loss-making entities", claim_id=1, query="Transfer pricing persistent losses commercial reasons"),
    ]}))
    plan = await evidence_planning.plan_evidence_search("Review transfer-pricing claims in a tax audit:\n" + "\n".join(claims), claims, claims=claims)
    assert plan.method == "semantic"
    assert [item.claim_id for item in plan.subjects] == [1, 2]
    assert all("Transfer pricing" in item.query for item in plan.subjects)
    assert "always" not in plan.subjects[1].query
    assert "Legal ownership always" in planner.await_args.kwargs["user"]


@pytest.mark.parametrize("payload", [
    {"subjects": [subject("A different subject", claim_id=1)]},
    {"subjects": [subject("One", claim_id=1), subject("Two", claim_id=1)]},
    {"subjects": [subject("One", claim_id=1), subject("Two", claim_id=2)], "requires_authority": False},
    {"subjects": [subject("One", claim_id=1, query="site:example.com rule"), subject("Two", claim_id=2)]},
    {"subjects": [subject("One", claim_id=1, query="France tax law"), subject("Two", claim_id=2)]},
])
async def test_incomplete_or_policy_widening_plans_fall_back_without_dropping_claims(planner, payload):
    planner.return_value = SimpleNamespace(text=json.dumps(payload))
    claims = ["Tax claim one.", "Tax claim two."]
    plan = await evidence_planning.plan_evidence_search("Check UK tax claims", claims, claims=claims)
    assert plan.method == "fallback" and len(plan.subjects) == 2


async def test_search_plans_cannot_collapse_explicit_topics(planner):
    planner.return_value = SimpleNamespace(text=json.dumps({"subjects": [subject("Only one subject")]}))
    plan = await evidence_planning.plan_evidence_search("Compare three topics", ["First topic", "Second topic", "Third topic"])
    assert plan.method == "fallback" and len(plan.subjects) == 3


async def test_planner_outage_keeps_search_available_and_shared_domain_context(planner):
    planner.side_effect = TimeoutError()
    plan = await evidence_planning.plan_evidence_search("Review tax claims", ["IP ownership returns"], claims=["IP ownership returns"])
    assert plan.method == "fallback"
    assert "tax" in plan.subjects[0].query


async def test_websearch_uses_neutral_subject_queries_and_alternatives(planner, monkeypatch):
    from app.orchestration import official_evidence, official_standards
    planner.return_value = SimpleNamespace(text=json.dumps({"subjects": [subject("First subject"), subject("Second subject")]}))
    monkeypatch.setattr(official_evidence, "official_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(official_standards, "official_standard_excerpts", AsyncMock(return_value=[]))
    calls = []
    async def search(query, **kwargs):
        calls.append(query)
        return [] if query == "Second subject" else [websearch.WebSource(title=query, url="https://oecd.org/" + str(len(calls)), snippet=query)]
    monkeypatch.setattr(websearch, "web_search", search)
    result = await websearch.web_search_each("Contrast these two subjects in prose.")
    assert len(result) == 2
    assert set(calls) == {"First subject", "Second subject", "Second subject qualifications and exceptions"}


async def test_a_contradiction_uses_only_the_reference_bound_by_the_verifier(monkeypatch):
    monkeypatch.setattr(claim_verification, "verify_claims", AsyncMock(return_value=claim_verification.VerificationResult(
        checked=1, ran=True, rejected_ids=[1], evidence_refs={1: ["REF-3"]},
        contradicted=[claim_verification.Contradiction("Claim", "The relevant rule does not provide this entitlement.")],
    )))
    judge = claim_verification.verify_claims
    verdict = (await review_mode._judge_each(["Claim about intellectual property returns"], [
        ["[REF-1] Irrelevant handbook", "[REF-2] Unrelated draft", "[REF-3] Applicable guidance"]],
        context="Transfer pricing review"))[0]
    assert verdict.verdict == review_mode.INCORRECT and verdict.refs == ["REF-3"]
    assert "Transfer pricing review" in judge.await_args.args[2]


async def test_unbound_contradictions_are_not_presented_as_verified_corrections(monkeypatch):
    monkeypatch.setattr(claim_verification, "verify_claims", AsyncMock(return_value=claim_verification.VerificationResult(
        checked=1, ran=True, contradicted=[claim_verification.Contradiction("A claim", "Something different")],
        evidence_refs={1: ["REF-99"]},
    )))
    verdict = (await review_mode._judge_each(["A claim"], [["[REF-1] Retrieved guidance"]]))[0]
    assert verdict.verdict == review_mode.UNVERIFIED and verdict.refs == []


async def test_verifier_keeps_reference_bindings_for_contradictions(planner, monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    planner.return_value = SimpleNamespace(text=json.dumps({"results": [
        {"claim": 1, "verdict": "contradicted", "references": ["REF-2", "REF-99"], "evidence_says": "Not permitted."},
    ]}))
    result = await claim_verification.verify_claims(["The rule always permits this."], ["[REF-1] Context", "[REF-2] Not permitted."])
    assert result.ran and result.evidence_refs == {1: ["REF-2"]}


def test_negating_the_claim_is_never_partial_confirmation():
    assert not review_mode._restates_part_of("The standard requires this treatment", "The standard does not require this treatment")


def test_procedural_row_numbers_are_not_a_chart_dataset():
    table = "| # | Claim in the text | Verdict | Source |\n|---|---|---|---|\n| 1 | First claim | Incorrect | Guidance |\n| 2 | Second claim | Could not verify | — |"
    assert offer_chart(table) is None
    assert offer_chart("| ID | Status |\n|---|---|\n| 1 | Pending |\n| 2 | Complete |") is None


@pytest.mark.parametrize("verb", ["may", "might", "can", "could", "should"])
def test_declarative_modal_statements_offer_actions_without_becoming_unsolicited_research(verb):
    assert statement_not_question(f"Global audits {verb} focus on recurring losses.")
    assert statement_not_question(f"Explain why global audits {verb} focus on recurring losses.") is None


@pytest.mark.parametrize("rule", [
    "Maintain confidentiality in line with GDPR and local privacy laws.",
    "Review records required by the applicable regulations.",
    "Establish the treatment required by accounting standards.",
])
async def test_regulatory_obligations_cannot_hide_under_operational_headings(rule):
    answer = "### General operational guidance\n" + rule
    question = "Prepare an operational framework for a tax audit."
    assert operational_guidance_claims(answer, question) == []
    assert not (await verify_for_release(answer, question=question, evidence=[], requires_authority=True)).passed


async def test_process_subject_words_do_not_turn_optional_advice_into_legal_requirements():
    answer = "### General operational guidance\nEstablish a shared folder for tax correspondence.\nAppoint a coordinator for the tax team."
    result = await verify_for_release(answer, question="Prepare an operational framework for a tax audit.", evidence=[], requires_authority=True)
    assert result.passed and len(result.general_explanations) == 2


async def test_coverage_review_finds_missing_deliverables_independent_of_wording(planner):
    planner.return_value = SimpleNamespace(text='{"missing": ["team coordination", "correspondence management"]}')
    missing = await coverage_review.missing_requested_parts("Include coordination, correspondence and document collection.", "### General guidance\nCollect files.")
    assert missing == ["team coordination", "correspondence management"]


async def test_unrepaired_semantic_omissions_remain_partial_through_the_pipeline(pipeline, monkeypatch):
    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    monkeypatch.setattr(coverage_review, "missing_requested_parts", AsyncMock(return_value=["correspondence management"]))
    monkeypatch.setattr(service.model_gateway_service, "run_optional_completion", AsyncMock(return_value=""))
    pipeline.answers(AgentOutcome(text="### General operational guidance\nDesignate a response coordinator."))
    response, _ = await pipeline.ask("Prepare an operational framework for a tax audit including coordination and correspondence.")
    assert response.answer.completeness == "partial"
    assert any("correspondence management" in note for note in response.answer.limitations)


async def test_a_rejected_draft_can_be_repaired_into_verified_or_labelled_content(pipeline, monkeypatch):
    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import service
    monkeypatch.setattr(coverage_review, "missing_requested_parts", AsyncMock(side_effect=[["coordination", "correspondence"], []]))
    replacement = "### General operational guidance\nDesignate a response coordinator.\nCollect correspondence in a shared folder."
    repair = AsyncMock(return_value=replacement)
    monkeypatch.setattr(service.model_gateway_service, "run_optional_completion", repair)
    pipeline.answers(AgentOutcome(text="### General operational guidance\nMaintain confidentiality in line with GDPR and local privacy laws."))
    response, _ = await pipeline.ask("Prepare an operational framework for a tax audit including coordination and correspondence.")
    repair.assert_awaited_once()
    assert "Designate a response coordinator" in response.answer.text
    assert "GDPR" not in response.answer.text
    assert any("general explanation" in note.lower() for note in response.answer.limitations)


def test_unrelated_framework_sources_do_not_pass_tax_relevance_on_ownership_vocabulary():
    source = websearch.WebSource(title="Exposure Draft: Clarifications to IFRS 15", url="https://ifrs.org/draft", snippet="Legal ownership and intellectual property returns")
    assert not websearch._is_relevant("Transfer pricing intellectual property ownership returns", source)


async def test_official_pdf_passages_can_be_read_as_evidence():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 50 700 Td (Intercompany transactions require a functional analysis.) Tj ET')
    # PDF streams must be indirect objects; native readers correctly reject
    # an inline /Contents stream even though pypdf tolerates that fixture.
    page[NameObject('/Contents')] = writer._add_object(stream)
    body = io.BytesIO()
    writer.write(body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body.getvalue(), headers={"content-type": "application/pdf"}))) as client:
        text = await websearch._page_excerpt(client, "https://oecd.org/guidance.pdf", "intercompany functional analysis")
    assert "functional analysis" in text and "PDF page 1" in text


async def test_provider_quota_failure_is_explained_without_exposing_raw_provider_messages(monkeypatch):
    from app.domains.model_gateway.tools import web_tool
    monkeypatch.setattr(websearch, "tavily_status", lambda: {"paused": True, "reason": "HTTP 432: private provider details", "configured": True})
    monkeypatch.setattr(web_tool, "web_search_each", AsyncMock(return_value=[]))
    result = await web_tool._handle(web_tool.SearchWebArgs(query="Transfer pricing audit evidence"))
    assert result.error_code == "retrieval_unavailable"
    assert "usage limit" in result.content
    assert "private provider details" not in result.content
    assert "not proof" in result.content


async def test_tool_context_shares_its_budget_across_all_subjects(monkeypatch):
    from app.domains.model_gateway.tools import web_tool
    from app.domains.model_gateway.tool_registry import MAX_RESULT_CHARS
    sources = [websearch.WebSource(title=f"Subject {i}", url=f"https://oecd.org/{i}", snippet=("Background text. " * 250) + f"\nFunctional analysis for subject {i}.") for i in range(9)]
    monkeypatch.setattr(web_tool, "web_search_each", AsyncMock(return_value=sources))
    result = await web_tool._handle(web_tool.SearchWebArgs(query="functional analysis"))
    assert result.ok and len(result.content) <= MAX_RESULT_CHARS
    assert all(f"Subject {i}" in result.content for i in range(9))
    assert all(f"Functional analysis for subject {i}" in result.content for i in range(9))


async def test_provider_outage_participates_in_agent_repeat_search_suppression():
    from app.domains.model_gateway.tools.web_tool import SearchWebArgs
    from app.domains.model_gateway.tool_registry import ToolRegistry, ToolSpec, ToolResult
    from tests.test_agent_loop import ScriptedClient, _call, _reply, _run
    called = []
    async def unavailable(args):
        called.append(args.query)
        return ToolResult.failure("retrieval_unavailable", "Search provider usage limit exhausted.")
    registry = ToolRegistry()
    registry.register(ToolSpec(name="search_web", version="1", description="Search", args_model=SearchWebArgs,
                               handler=unavailable, data_source="test", risk_level="low", timeout_seconds=1))
    client = ScriptedClient([
        _reply(tool_calls=[_call("search_web", {"query": "transfer pricing documentation"}, "one")]),
        _reply(tool_calls=[_call("search_web", {"query": "documentation for transfer pricing"}, "two")]),
        *[_reply("The retrieved evidence does not establish the answer.") for _ in range(4)],
    ])
    result = await _run(client, registry)
    assert len(called) == 1
    assert [record.error_code for record in result.tool_calls][:2] == ["retrieval_unavailable", "repeat_search"]


@pytest.mark.parametrize("question", [
    "Contrast the audit topics and tell me how to get ready for each.",
    "What practical preparation steps would help?",
    "Give me a checklist of optional process improvements.",
])
async def test_safe_guidance_does_not_depend_on_operational_framework_wording(question):
    result = await verify_for_release("### General operational guidance\nCollect correspondence in a shared folder.",
                                     question=question, evidence=[], requires_authority=True)
    assert result.passed and result.general_explanations
