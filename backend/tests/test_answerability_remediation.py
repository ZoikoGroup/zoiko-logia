"""Answerability remediation: regression tests for the root causes confirmed
from the execution traces of 2026-10-16 (request ids in each test)."""
import json
import re
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import WITHHELD_NOTICE, AgentOutcome
from app.orchestration import claim_verification, service
from app.orchestration.agent_plan import plan_request
from app.orchestration.calculations.engine import change_followup
from app.orchestration.input_requirements import references_attachment
from app.orchestration.verification_service import (
    _from_verified_calculation, _period_mismatch, calculated_figures, release_claims, verify_for_release,
)
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture

OLD = N(role="user", content="Revenue is £850,000 and cost of sales is £510,000. Calculate gross profit.")
FORECAST = N(role="user", content="Our current annual revenue is £2,400,000, variable costs are 45% of revenue, "
                                  "and annual fixed operating costs are £780,000.")


# ── Root cause 5: follow-ups never borrow another scenario's figures ───────

def test_a_forecast_follow_up_is_not_answered_from_an_older_scenario():
    # qry-6941f17bd98f: "revenue +12%, variable costs stay 45%, fixed costs +£60,000 … operating profit"
    # was answered as a gross-profit change on £850,000/£510,000 from an earlier, unrelated question.
    question = ("Now model a scenario where revenue increases by 12%, the variable-cost percentage stays at 45%, "
                "and fixed operating costs increase by £60,000. Calculate the revised operating profit.")
    assert change_followup(question, [OLD, N(role="assistant", content="…"), FORECAST]) is None


def test_the_latest_scenario_is_the_task_boundary():
    assert change_followup("What if revenue increases by 12%?", [OLD, FORECAST]) is None


def test_a_follow_up_on_the_current_scenario_still_calculates():
    result = change_followup("What if revenue increases by 10%?", [FORECAST, OLD])     # OLD is the latest scenario
    assert {o.name: float(o.value) for o in result.outputs}["revenue"] == 935000.0


def test_figures_written_by_kriton_are_not_user_inputs():
    kriton = N(role="assistant", content="Revenue is £999,999 and cost of sales is £111,111.")
    result = change_followup("What if revenue increases by 10%?", [OLD, kriton])
    assert {o.name: float(o.value) for o in result.outputs}["revenue"] == 935000.0


def test_a_change_to_one_assumption_and_a_chain_of_changes_still_work():
    two_step = [N(role="user", content="Revenue £300,000, cost of sales £180,000."),
                N(role="user", content="Now assume revenue grows by 10%.")]
    result = change_followup("And if cost of sales also rises by 5% on top of that, what is the gross profit?", two_step)
    assert {o.name: float(o.value) for o in result.outputs}["gross_profit"] == 141000.0


# ── Root cause 1: a withheld answer keeps its verified working ─────────────

def test_the_withheld_notice_and_its_working_are_not_claims():
    # qry-f7c7ad8f72ff: the notice was rejected as an uncited claim and the answer became "none".
    answer = WITHHELD_NOTICE + "\n\nHere is the verified working:\n\n1215000 - 710000 = 505000"
    assert release_claims(answer) == []


async def test_a_withheld_answer_is_released_as_partial_with_its_working(pipeline):
    pipeline.answers(AgentOutcome(text=WITHHELD_NOTICE + "\n\nHere is the verified working:\n\n1215000 - 710000 = 505000",
                                  unreconciled_figures=["£12,345"]))
    response, audited = await pipeline.ask("What VAT rules apply to a 1,215,000 revenue UK manufacturer? Calculate "
                                           "gross profit on £1,215,000 sales and £710,000 cost of goods sold.")
    assert "1215000 - 710000 = 505000" in response.answer.text
    assert audited.completeness == "partial"


def test_a_long_multi_deliverable_request_gets_a_bounded_step_allowance():
    long_request = ("I need a detailed financial performance analysis. " + "Figures: £1,250,000. " * 40
                    + "Please calculate net sales, compare years, explain changes, identify gaps, provide a table, "
                      "prepare a chart and give five recommendations.")
    assert service.deliverable_step_allowance(long_request) == 4
    assert service.deliverable_step_allowance("Calculate gross margin on £100 and £60.") == 0


# ── Root cause 8: the user's own scenario worked out needs no research source ─

FX_QUESTION = ("We expect to pay US$125,000 in 60 days. Our approved budget rate is £1 = US$1.25. "
               "Explain the impact if the rate moves to £1 = US$1.20 or £1 = US$1.30.")
RECEIPTS = [{"expression": "125000/1.25", "result": "100000"}, {"expression": "125000/1.2", "result": "104166.666667"},
            {"expression": "125000/1.3", "result": "96153.846154"}]


@pytest.mark.parametrize("row, exempt", [
    ("| Budget rate ( £1 = US$1.25 ) | 0.80 | 100,000 |", True),
    ("| Scenario 1 ( £1 = US$1.20 ) | 0.833333 | 104,166.666667 |", True),
    # A live market figure is evidence and keeps its citation requirement.
    ("| Market rate ( 1 GBP = 1.3246661 USD ) | 0.754907 | 94,363.402219 |", False),
    # A tax rate asserted as fact still needs a source.
    ("The standard rate of VAT is 20%.", False),
])
def test_scenario_rows_from_the_users_rates_are_calculations(row, exempt):
    # qry-3b42c1c9fc1b: every scenario row was removed as "uncited".
    assert _from_verified_calculation(row, calculated_figures(None, question=FX_QUESTION, receipts=RECEIPTS)) is exempt


# ── Root cause 7: a referenced attachment that never arrived is asked for ──

@pytest.mark.parametrize("question, expected", [
    ("Please review the attached annual financial report for the company.", True),
    ("Using the attached balance sheet, what is the current ratio?", True),
    ("Review our uploaded trial balance", True),
    ("What should an attached report contain?", False),
])
def test_a_reference_to_an_attached_file_is_recognised(question, expected):
    assert references_attachment(question) is expected


async def test_no_web_search_for_an_attachment_that_never_arrived(pipeline, monkeypatch):
    # qry-4cdb1fec3966: no document reached the backend, the web was searched, "insufficient evidence".
    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=[]))
    response, audited = await pipeline.ask("Please review the attached annual financial report and calculate the "
                                           "gross margin.")
    assert audited.outcome == "clarification_required"
    assert "attach it again" in response.next_action.message
    pipeline.agent.assert_not_awaited()


# ── Root cause 6: open questions are not claims; past periods need period evidence ─

ISLE_OF_MAN = ("I need to establish the VAT registration threshold that applied in the Isle of Man between March "
               "1987 and March 1988.")


def test_open_questions_and_research_steps_are_not_claims():
    answer = ("- Whether the UK thresholds of £20,500 and £21,300 automatically applied in the Isle of Man is unresolved.\n"
              "- To establish the exact threshold, an authoritative historical Manx source is required.\n"
              "- Until such a source is located, the UK figures should be reported only as UK thresholds.\n"
              "- The UK statutory instrument you mention is not provided in the sources.\n"
              "- Revenue should be treated as deferred income [REF-1].")
    assert release_claims(answer) == ["Revenue should be treated as deferred income [REF-1]."]


@pytest.mark.parametrize("claim, question, mismatch", [
    ("The current UK registration threshold is £90,000 [REF-1].", ISLE_OF_MAN, True),
    ("From 18 March 1987 the UK threshold was £21,300 [REF-1].", ISLE_OF_MAN, False),
    ("The current threshold is £90,000 [REF-1].", "What is the current VAT threshold?", False),
])
def test_todays_position_does_not_answer_a_past_period(claim, question, mismatch):
    assert _period_mismatch(claim, question) is mismatch


@pytest.fixture
def supportive_verifier(monkeypatch):
    async def complete_auxiliary(*, user, **_):
        claims = re.findall(r"^(\d+)\. ", user.split("\n\nCLAIMS:\n", 1)[1], re.M)
        return N(text=json.dumps({"results": [{"claim": int(n), "verdict": "supported", "references": ["REF-1"],
                                               "evidence_says": ""} for n in claims]}))
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(claim_verification, "gateway", N(may_use=lambda *a, **k: True, complete_auxiliary=complete_auxiliary))


async def test_a_current_figure_for_a_past_period_is_rejected_before_any_model_judgement(supportive_verifier):
    check = await verify_for_release("The current UK registration threshold is £90,000 [REF-1].", question=ISLE_OF_MAN,
                                     evidence=["[REF-1] The registration threshold is £90,000."], requires_authority=True)
    assert not check.passed and check.rejected_reasons == ["effective_date_mismatch"]


# ── Root cause D2: what the user excludes is not a topic ───────────────────

def test_an_excluded_topic_does_not_plan_research():
    # qry-58ce336ac0d7: "Ignore interest, tax and depreciation" planned a tax search.
    question = ("Our current annual revenue is £2,400,000, variable costs are 45% of revenue, and annual fixed "
                "operating costs are £780,000. Ignore interest, tax and depreciation for this simplified model. "
                "Calculate current contribution, operating profit, contribution margin and break-even revenue.")
    assert plan_request(question).tools == ("calculate",)
    assert "search_web" in plan_request("Calculate corporation tax on £300,000 of profit.").tools


def test_restating_the_users_figures_is_still_a_claim():
    # Only a computed result is calculator output; a sentence that merely repeats a user's figure needs a source.
    figures = calculated_figures(None, question="A customer paid £120,000 upfront for 12 months.",
                                 receipts=[{"expression": "120000/12", "result": "10000"}])
    assert not _from_verified_calculation("The £120,000 is recognised as revenue on day one.", figures)
    assert _from_verified_calculation("Monthly revenue = £120,000 ÷ 12 = £10,000", figures)


# ── Review follow-ups (engineering review, 2026-10-16) ─────────────────────

@pytest.mark.parametrize("question, researches", [
    ("Ignore interest, tax and depreciation. Calculate operating profit on £500,000 revenue and £320,000 costs.", False),
    ("Disregard VAT for now and calculate gross margin on £100,000 revenue and £60,000 cost of sales.", False),
    ("Calculate corporation tax on £300,000 of profit.", True),                 # genuine tax question
    ("What does 'reverse charge VAT' mean for UK services?", False),           # simple concept question, unchanged
])
def test_excluded_tax_wording_is_not_a_tax_question_but_genuine_ones_are(question, researches):
    tools = plan_request(question).tools
    assert ("search_web" in tools or "search_knowledge_base" in tools) is researches


@pytest.mark.parametrize("found", [["doc-in-this-request"], ["doc-attached-earlier-in-the-conversation"]])
async def test_an_attachment_in_the_request_or_conversation_is_not_asked_for(pipeline, monkeypatch, found):
    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=found))
    pipeline.answers(AgentOutcome(text="Gross margin = 40%."))
    response, audited = await pipeline.ask("Please review the attached annual financial report and calculate the "
                                           "gross margin.")
    assert not (response.next_action and "attach it again" in response.next_action.message)


async def test_extra_steps_keep_the_time_budget_tool_cap_and_policy(monkeypatch):
    from app.domains.model_gateway import service as gateway_service
    seen = {}

    async def fake_run_agent(client, **kwargs):
        seen.update(kwargs)
        return AgentOutcome(text="ok")
    monkeypatch.setattr(gateway_service, "run_agent", fake_run_agent)
    monkeypatch.setattr(gateway_service, "approved_providers", lambda: {"groq"})
    monkeypatch.setattr(gateway_service, "GroqAdapter", lambda: N(client=object()))
    authorize = AsyncMock()
    settings = gateway_service.get_settings()
    await gateway_service.run_agentic_completion("q", granted_permissions=frozenset(), max_seconds=30.0,
                                                 extra_steps=4, authorize=authorize)
    limits = seen["limits"]
    assert limits.max_steps == settings.AGENT_MAX_STEPS + 4
    assert limits.max_tool_calls == settings.AGENT_MAX_TOOL_CALLS + 6           # bounded, not unlimited
    assert limits.max_seconds == min(settings.AGENT_MAX_SECONDS, 30.0)        # the time budget is unchanged
    assert limits.max_total_tokens == settings.AGENT_MAX_TOKENS                # so is the token budget
    assert seen["authorize"] is authorize                                     # every call still goes through policy


def test_each_calculated_row_traces_to_a_receipt_from_the_users_rate():
    figures = calculated_figures(None, question=FX_QUESTION, receipts=RECEIPTS)
    assert "100000.00" in figures.results and "1.25" in figures.inputs        # 125000 / 1.25 = 100000
    # A row whose result no calculation produced is not exempt, even on the user's rate.
    assert not _from_verified_calculation("| Budget rate ( £1 = US$1.25 ) | 0.80 | 101,000 |", figures)


async def test_a_historical_rule_still_needs_its_own_authoritative_source(supportive_verifier):
    # The period check does not exempt a historical claim: uncited, it is rejected.
    check = await verify_for_release("From 18 March 1987 the Isle of Man threshold was £21,300.", question=ISLE_OF_MAN,
                                     evidence=["[REF-1] UK limits table."], requires_authority=True)
    assert not check.passed and check.rejected_reasons == ["missing_citation"]


def test_a_deadline_question_keeps_its_evidence_requirement():
    # A simple question has no agent tools; its sources are pre-fetched and the release check
    # still requires authoritative evidence for it.
    from app.orchestration.agent_plan import GENERAL_GUIDANCE_REASON
    from app.orchestration.verification_service import requires_authoritative_evidence
    question = "When is the VAT return due for the quarter ending 31 March?"
    assert requires_authoritative_evidence(question)
    assert GENERAL_GUIDANCE_REASON not in plan_request(question).reasons


# ── Decision C: general explanation is kept and labelled, not deleted ──────

BANK_QUOTE = "An executable bank quote includes the bank's spread and settlement terms."


@pytest.fixture
def evidence_verifier(monkeypatch):
    """Supported only when the claim's text is in the evidence shown; one
    statement can be marked contradicted."""
    state = N(contradict="")

    async def complete_auxiliary(*, user, **_):
        evidence = user.split("EVIDENCE:\n", 1)[1].split("\n\nCLAIMS:\n", 1)[0].lower()
        results = []
        for number, claim in re.findall(r"^(\d+)\. (.*)$", user.split("\n\nCLAIMS:\n", 1)[1], re.M):
            bare = re.sub(r"\s*\[REF-\d+\]", "", claim).strip().rstrip(".").lower()
            if state.contradict and state.contradict.lower() in claim.lower():
                results.append({"claim": int(number), "verdict": "contradicted", "references": [], "evidence_says": "x"})
            elif bare and bare in evidence:
                results.append({"claim": int(number), "verdict": "supported", "references": ["REF-1"], "evidence_says": ""})
            else:
                results.append({"claim": int(number), "verdict": "not_in_evidence", "references": [], "evidence_says": ""})
        return N(text=json.dumps({"results": results}))
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(claim_verification, "gateway", N(may_use=lambda *a, **k: True, complete_auxiliary=complete_auxiliary))
    return state


EVIDENCE = ["[REF-1] The ECB reference rate on 2026-10-15 was 1 GBP = 1.3246661 USD."]


async def test_general_background_the_sources_do_not_cover_is_kept(evidence_verifier):
    # qry-3b42c1c9fc1b: the reference-rate vs bank-quote explanation was removed as unsourced.
    answer = ("The ECB reference rate on 2026-10-15 was 1 GBP = 1.3246661 USD [REF-1].\n"
              f"{BANK_QUOTE} [REF-1]")
    check = await verify_for_release(answer, question="FX question", evidence=EVIDENCE, requires_authority=True)
    assert check.passed and check.general_explanations == [f"{BANK_QUOTE} [REF-1]"]


async def test_general_text_alone_does_not_answer_a_question_that_needs_a_source(evidence_verifier):
    # Background is kept beside a real answer, never instead of one.
    assert not (await verify_for_release(BANK_QUOTE, question="FX question", evidence=[], requires_authority=True)).passed
    assert not (await verify_for_release(f"{BANK_QUOTE} [REF-1]", question="FX question", evidence=EVIDENCE,
                                         requires_authority=True)).passed


@pytest.mark.parametrize("statement", [
    "The standard VAT rate is 20% [REF-1].",                      # a rate
    "Revenue is recognised when control transfers [REF-1].",      # accounting treatment
    "In the UK, companies file accounts annually [REF-1].",       # a jurisdiction
    "Bank quotes added £1,200 in fees last year [REF-1].",        # a figure
])
async def test_specific_claims_keep_their_evidence_requirement(evidence_verifier, statement):
    check = await verify_for_release(statement, question="q", evidence=EVIDENCE, requires_authority=True)
    assert not check.passed and statement in check.rejected_claims


async def test_a_contradicted_general_statement_is_still_removed(evidence_verifier):
    evidence_verifier.contradict = "settlement terms"
    check = await verify_for_release(f"{BANK_QUOTE} [REF-1]", question="q", evidence=EVIDENCE, requires_authority=True)
    assert not check.passed and check.rejected_reasons == ["contradicted_by_cited_source"]


async def test_kept_background_is_labelled_and_loses_its_unsupported_citation(pipeline, evidence_verifier):
    from app.orchestration.websearch import WebSource
    ecb = WebSource(title="ECB reference rates", url="https://www.ecb.europa.eu/stats/eurofxref", snippet=EVIDENCE[0][8:],
                    provider="ECB", freshness="daily")
    pipeline.answers(AgentOutcome(text="The ECB reference rate on 2026-10-15 was 1 GBP = 1.3246661 USD [REF-1].\n"
                                       f"{BANK_QUOTE} [REF-1]", sources=[ecb]))
    # Routed through the agent, as the live FX question was (a "How does …" opener takes the simple path).
    response, audited = await pipeline.ask("Compare the GBP/USD reference rate published on 15 October 2026 with a "
                                           "bank's executable quote, and cite the VAT rules that apply.")
    assert BANK_QUOTE in response.answer.text and f"{BANK_QUOTE} [REF-1]" not in response.answer.text
    assert any("general explanation, not verified against a source" in item for item in response.answer.limitations)
