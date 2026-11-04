"""Fixes from the 29-30 Oct 2026 live retrieval test.

Q6. "Convert £10,000 to euros at today's exchange rate." read as facts with
    nothing asked ("convert" was no request word), so the next, unrelated
    question ("What is the current UK Bank Rate?") was resolved as its
    follow-up and carried its facts.
Q7. "What is deferred tax and why does it arise?" was a tax topic only, so
    search was limited to oecd.org and the answer brought in Pillar Two; an
    IFRS answer's "valuation allowance" (ASC 740) was not seen as US GAAP.
Q10. "What interest rate does HMRC charge on late VAT payments?" (agent mode)
    read HMRC's "Bank Rate plus 4%" but had no Bank Rate: the agent has no
    Bank of England tool and Bank Rate was pre-fetched only for "bank rate"
    wording.
No model, database or network.
"""
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import conversation_resolver as cr, service
from app.orchestration.framework_scope import foreign_framework_statements
from app.orchestration.live_data import LiveDataResult
from app.orchestration.official_prefetch import bank_rate_prefetch
from app.orchestration.schemas import ConversationMessage
from app.orchestration.source_taxonomy import allowed_domains, detect_topics
from app.orchestration.task_contract import build_task_contract
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


def _after(previous, answer, query):
    history = [ConversationMessage(role="user", content=previous), ConversationMessage(role="assistant", content=answer)]
    return cr.resolve_conversation(query, history)


# Q6 -------------------------------------------------------------------------

def test_a_question_after_a_conversion_is_not_its_follow_up():
    resolution = _after("Convert £10,000 to euros at today's exchange rate.", "£10,000 × 1.1964871 = €11,964.87",
                        "What is the current UK Bank Rate?")
    assert resolution.kind == "standalone"


@pytest.mark.parametrize("text", [
    "Convert £10,000 to euros at today's exchange rate.",
    "Convert 5,000 USD to INR, EUR and GBP at today's rate.",
    "Our UK company invoiced a German client €40,000. Convert it to pounds at the latest rate.",
    "Draw a pie chart of our profit: Q1 £20,000, Q2 -£5,000, Q3 £12,000.",
    "Pass the journal entry for depreciation of ₹50,000 on machinery.",
    "Pie chart of marketing budget: digital £45,000, print £15,000, events £25,000, PR £15,000",
    "Stacked bar chart of quarterly revenue (£k) by product — Q1: A 50, B 30, C 20",
    "Diagram the UK VAT registration decision: turnover over £90,000 in 12 months → must register",
    "Chart the USD to INR exchange rate over the last 12 months",
])
def test_these_requests_ask_something(text):
    assert cr.asks_something(text) and not cr.is_scenario_only(text)


@pytest.mark.parametrize("text", [
    "We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years.",
    "Chart of accounts codes 4000 to 4999 hold revenue of £20,000.",
    "Graph of sales: Q1 £10,000, Q2 £12,000 shows growth.",
])
def test_facts_set_out_are_still_a_scenario(text):
    assert not cr.asks_something(text)


def test_a_scenario_still_takes_its_question():
    resolution = _after("We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years.",
                        "Noted.", "What is the discount rate?")
    assert resolution.kind == "follow_up"


# Q7 -------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["What is deferred tax and why does it arise?", "What is a deferred tax asset?",
                                   "Explain temporary differences and the tax base of an asset."])
def test_deferred_tax_is_searched_on_the_standard_setters(query):
    domains = allowed_domains("", detect_topics(query), query)
    assert "ifrs.org" in domains


def test_a_tax_rate_question_keeps_its_tax_authorities():
    assert detect_topics("What is the UK corporation tax rate?") == {"tax"}


def test_valuation_allowance_is_us_gaap_wording_in_an_ifrs_answer():
    answer = ("Deferred tax is measured under IAS 12.\n"
              "A deferred tax asset is recognised when probable; otherwise, a valuation allowance is required.")
    assert foreign_framework_statements("Explain deferred tax under IFRS.", answer, []) == [
        "A deferred tax asset is recognised when probable; otherwise, a valuation allowance is required."]
    assert foreign_framework_statements("What is deferred tax?", answer, []) == []      # no framework named


# Q10 ------------------------------------------------------------------------

@pytest.mark.parametrize("query, expected", [
    ("What interest rate does HMRC charge on late VAT payments?", True),
    ("What is the HMRC late payment interest rate for self assessment?", True),
    ("What interest rate is charged on unpaid corporation tax?", True),
    ("A loan of £40,000 carries interest at 6%. Calculate the interest.", False),
    ("What is the standard rate of VAT in the UK?", False),
    ("What is the interest rate implicit in a lease?", False),
    ("What penalty applies if I pay my VAT 20 days late?", False),
    ("What interest does the IRS charge on late payments?", False),
])
def test_bank_rate_is_wanted_for_hmrcs_interest_rates_only(query, expected):
    assert bank_rate_prefetch(build_task_contract(query)) is expected
    assert bank_rate_prefetch(None) is False


async def test_agent_mode_fetches_bank_rate_for_hmrc_interest(pipeline, monkeypatch):
    fetch = AsyncMock(return_value=LiveDataResult())
    monkeypatch.setattr(service, "fetch_live_data", fetch)
    pipeline.answers(AgentOutcome(text="HMRC charges late payment interest."))
    await pipeline.ask("What interest rate does HMRC charge on late VAT payments?")
    assert pipeline.agent.await_count == 1          # the agent loop, where Bank Rate was missing
    fetch.assert_awaited_once()


async def test_agent_mode_fetches_no_bank_rate_for_another_official_rate(pipeline, monkeypatch):
    # A question the agent loop answers, with an official rate HMRC does not set.
    fetch = AsyncMock(return_value=LiveDataResult())
    monkeypatch.setattr(service, "fetch_live_data", fetch)
    pipeline.answers(AgentOutcome(text="Singapore's GST rate is 9%."))
    await pipeline.ask("Singapore GST rate in 2026?")
    assert pipeline.agent.await_count == 1
    fetch.assert_not_awaited()


def _bank_rate_result():
    """The Bank of England result as it arrived live: a source and a dated series."""
    from app.orchestration.evidence import EvidenceModel, Observation
    from app.orchestration.websearch import WebSource
    evidence = EvidenceModel()
    evidence.subject = "UK Bank Rate"
    evidence.observations.extend(Observation(dimension=day, value=value, measure="UK Bank Rate")
                                 for day, value in (("2025-10-30", 4.0), ("2025-12-18", 3.75), ("2026-10-28", 3.75)))
    evidence.dimensions.append("period")
    evidence.measures.append("UK Bank Rate")
    evidence.units.append("%")
    evidence.provider = "Bank of England"
    evidence.series_id = "IUDBEDR"
    source = WebSource(title="Bank of England: Bank Rate", url="https://www.bankofengland.co.uk/boeapps/database/",
                       snippet="Bank Rate is 3.75% (latest observation 2026-10-28), unchanged since 2025-12-18.",
                       provider="Bank of England", freshness="current")
    return LiveDataResult(sources=[source], evidence=evidence)


async def test_bank_rate_is_evidence_for_hmrc_interest_not_the_answer(pipeline, monkeypatch):
    # Live, 30 Oct 2026: the series became the whole answer ("Across 252
    # source-grounded observations, UK Bank Rate decreased …").
    monkeypatch.setattr(service, "fetch_live_data", AsyncMock(return_value=_bank_rate_result()))
    pipeline.answers(AgentOutcome(text="HMRC charges late payment interest at Bank Rate plus 4%."))
    response, _ = await pipeline.ask("What interest rate does HMRC charge on late VAT payments?")
    assert pipeline.agent.await_count == 1
    assert "Bank Rate is 3.75%" in pipeline.agent.await_args.args[0]          # the source reached the model
    text = response.answer.text if response.answer else ""
    assert "source-grounded observations" not in text
    assert response.visualization is None


async def test_a_bank_rate_series_question_is_still_narrated_from_the_series(pipeline, monkeypatch):
    monkeypatch.setattr(service, "fetch_live_data", AsyncMock(return_value=_bank_rate_result()))
    pipeline.answers(AgentOutcome(text="Model text."))
    response, _ = await pipeline.ask("Show the Bank of England base rate over the last 3 years as a line chart")
    assert "source-grounded observations" in (response.answer.text if response.answer else "")


# Q10: HMRC's interest-rate page as a fixed official page --------------------

HMRC_INTEREST_PAGE = "HMRC: Interest rates for late and early payments"


@pytest.mark.parametrize("query, selected", [
    ("What interest rate does HMRC charge on late VAT payments?", True),
    ("What repayment interest does HMRC pay on overpaid VAT?", True),
    ("What interest is charged on unpaid self assessment tax?", True),
    ("What interest does the IRS charge on late payments?", False),
    ("A loan of £40,000 carries interest at 6%. Calculate the interest.", False),
    ("What is the standard rate of VAT in the UK?", False),
    ("What penalty applies if I pay my VAT 20 days late?", False),
])
def test_the_hmrc_interest_page_is_read_for_hmrc_interest_questions_only(query, selected):
    from app.orchestration.official_evidence import official_pages
    assert (HMRC_INTEREST_PAGE in [title for title, _ in official_pages(query)]) is selected


async def test_agent_mode_composes_hmrc_interest_with_the_rate_page(pipeline, monkeypatch):
    from app.orchestration import official_evidence
    from app.orchestration.websearch import WebSource
    page = WebSource(title=HMRC_INTEREST_PAGE, url="https://www.gov.uk/government/publications/rates-and-allowances-hmrc-interest-rates",
                     snippet="Late payment interest is charged at the Bank of England base rate plus 4%.",
                     provider="HMRC", freshness="current")
    monkeypatch.setattr(official_evidence, "official_sources", AsyncMock(return_value=[page]))
    monkeypatch.setattr(service, "fetch_live_data", AsyncMock(return_value=_bank_rate_result()))
    pipeline.answers(AgentOutcome(text="HMRC charges late payment interest at Bank Rate plus 4%."))
    await pipeline.ask("What interest rate does HMRC charge on late VAT payments?")
    prompt = pipeline.agent.await_args.args[0]
    assert "base rate plus 4%" in prompt and "Bank Rate is 3.75%" in prompt      # the rule and the rate it needs
