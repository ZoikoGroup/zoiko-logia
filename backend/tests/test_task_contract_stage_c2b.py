"""Task Contract, Stage C-2b: retrieval follows the contract's official
requirements.

1. Agent mode reads the existing fixed official pages for the parts the
   contract says need an official figure or rule (official_prefetch.py);
   nothing for conceptual questions or calculations, and nothing new in the
   standard path.
2. A statistics or central-bank connector is not called for a question it
   cannot answer (connector_scope.py).
3. The "no source was cited" note names the named country's authority, never
   another country's.
Connectors and pages are stubbed: no model, database or network.
"""
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import live_data, official_evidence, service, websearch
from app.orchestration.connector_scope import applies
from app.orchestration.official_prefetch import official_prefetch, official_prefetch_plan
from app.orchestration.source_guarantee import official_sources_note
from app.orchestration.task_contract import build_task_contract
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

IRAS = WebSource(title="IRAS: Current GST rates", url="https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/basics-of-gst/current-gst-rates",
                 snippet="The GST rate is 9% from 1 January 2024.", provider="IRAS", freshness="current")
HMRC = WebSource(title="HMRC: When to register for VAT", url="https://www.gov.uk/register-for-vat",
                 snippet="You must register if your total taxable turnover for the last 12 months goes over £90,000.",
                 provider="GOV.UK (HMRC)", freshness="current")


@pytest.fixture
def pages(monkeypatch):
    calls = {"official": [], "hmrc": 0}

    async def official(question):
        calls["official"].append(question)
        return [IRAS] if "singapore" in question.lower() else []

    async def hmrc():
        calls["hmrc"] += 1
        return [HMRC]
    monkeypatch.setattr(official_evidence, "official_sources", official)
    monkeypatch.setattr(websearch, "_uk_vat_rules_source", hmrc)
    return calls


# 1. The plan: from the contract's official parts only ----------------------------

@pytest.mark.parametrize("query, texts, hmrc", [
    ("What is the current UK VAT registration threshold?", 0, True),
    ("What is the standard GST rate in Singapore?", 1, False),
    ("What is the main rate of corporation tax in the UK for 2026?", 1, False),
    ("I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. Do I need GST registration "
     "and do I charge GST?", 1, False),
])
def test_an_official_part_with_a_fixed_page_is_planned(query, texts, hmrc):
    planned, registration = official_prefetch_plan(build_task_contract(query))
    assert len(planned) == texts and registration is hmrc


@pytest.mark.parametrize("query", [
    "Explain how VAT works as a tax on consumption.",
    "Why do tax authorities set VAT registration thresholds?",
    "Explain the difference between tax avoidance and tax evasion.",
    "Calculate the VAT payable: UK company, sales £100,000, purchases £50,000, VAT 20%, figures exclude VAT, "
    "all standard-rated.",
    "A Singapore company invoiced services of S$10,000 plus GST at 9%. Calculate the GST to charge.",
    "What is the GST rate on restaurant services in India?",       # official, but no fixed page covers it
    "Convert £10,000 to euros at today's exchange rate.",          # the exchange-rate connector, not a page
    "What is the current UK Bank Rate?",                           # already pre-fetched in agent mode
])
def test_nothing_is_planned_without_an_official_part_a_fixed_page_covers(query):
    assert official_prefetch_plan(build_task_contract(query)) == ([], False)
    assert official_prefetch_plan(None) == ([], False)


async def test_the_prefetch_reads_the_planned_pages_once_each(pages):
    sources = await official_prefetch(build_task_contract("What is the standard GST rate in Singapore?"))
    assert sources == [IRAS] and len(pages["official"]) == 1 and pages["hmrc"] == 0
    sources = await official_prefetch(build_task_contract("What is the current UK VAT registration threshold?"))
    assert sources == [HMRC] and pages["hmrc"] == 1
    assert await official_prefetch(build_task_contract("Explain how VAT works as a tax on consumption.")) == []


async def test_a_failing_page_contributes_nothing(monkeypatch):
    monkeypatch.setattr(official_evidence, "official_sources", AsyncMock(side_effect=RuntimeError("down")))
    assert await official_prefetch(build_task_contract("What is the standard GST rate in Singapore?")) == []


# 1. In the pipeline: agent mode only -------------------------------------------

async def test_agent_mode_composes_with_the_official_page(pipeline, pages):
    # A question the agent loop answers (a bare "What is the standard GST rate
    # in Singapore?" takes the standard path, which already reads the page).
    pipeline.answers(AgentOutcome(text="Singapore's standard GST rate is 9% [REF-1]."))
    await pipeline.ask("Singapore GST rate in 2026?")
    assert len(pages["official"]) == 1
    assert "The GST rate is 9% from 1 January 2024." in pipeline.agent.await_args.args[0]


async def test_agent_mode_reads_hmrcs_registration_page_for_the_threshold(pipeline, pages):
    pipeline.answers(AgentOutcome(text="The threshold is set by HMRC [REF-1]."))
    await pipeline.ask("What is the current UK VAT registration threshold?")
    assert pages["hmrc"] == 1 and "goes over £90,000" in pipeline.agent.await_args.args[0]


@pytest.mark.parametrize("query", ["Explain how VAT works as a tax on consumption.",
                                   "Why do tax authorities set VAT registration thresholds?",
                                   "What is deferred tax and why does it arise?"])
async def test_agent_mode_reads_no_page_for_a_conceptual_question(pipeline, pages, query):
    pipeline.answers(AgentOutcome(text="A general explanation."))
    await pipeline.ask(query)
    assert pages == {"official": [], "hmrc": 0}


async def test_the_standard_path_is_unchanged(pipeline, pages, monkeypatch):
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: False)
    prefetch = AsyncMock(return_value=[])
    import app.orchestration.official_prefetch as module
    monkeypatch.setattr(module, "official_prefetch", prefetch)
    pipeline.answers(AgentOutcome(text="Answer."))
    await pipeline.ask("What is the standard GST rate in Singapore?")
    prefetch.assert_not_awaited()
    service.web_search_each.assert_awaited()        # the standard path's own retrieval, as before


# 2. Connector applicability ------------------------------------------------------

@pytest.mark.parametrize("connector, query", [
    ("bank_of_england", "What is the current UK Bank Rate?"),
    ("bank_of_england", "What interest rate does HMRC charge on late VAT payments?"),   # base rate + 4%
    ("bank_of_canada", "What is the current Bank of Canada policy rate?"),
    ("rba", "What is the RBA cash rate?"),
    ("bank_of_canada", "What is the current policy rate?"),          # unscoped: each connector's default, as before
    ("dbnomics", "What is UK inflation?"),
    ("dbnomics", "What is the tax-to-GDP ratio in India and Brazil?"),
    ("dbnomics", "UK government debt as a percentage of GDP"),
    ("govuk_tax_rate", "What is the main rate of corporation tax in the UK for 2026?"),
    ("govuk_tax_rate", "What is 18% GST on ₹50,000? Also, what is the UK VAT rate?"),
    ("abs", "Plot Australia's inflation over the last 10 years."),
    ("dbnomics", "What were India's total exports in 2025?"),
])
def test_a_connector_still_applies_to_its_own_questions(connector, query):
    assert applies(connector, query)


@pytest.mark.parametrize("connector, query", [
    ("bank_of_canada", "What interest rate does HMRC charge on late VAT payments?"),
    ("rba", "What interest rate does HMRC charge on late VAT payments?"),
    ("bank_of_canada", "What is the RBA cash rate?"),
    ("bank_of_england", "Kestrel Logistics Ltd reports under IFRS. Annual payments of £24,000 are paid at the end of "
                        "each year, and the interest rate implicit in the lease is 7%."),
    ("dbnomics", "How long must a debt be outstanding before I can claim VAT bad debt relief?"),
    ("dbnomics", "What is the 2026 Social Security wage base in the US?"),
    ("dbnomics", "Total debt is 2.4 million and total equity is 3 million. What is the debt-to-equity ratio?"),
    ("dbnomics", "What is the corporation tax rate in the UK?"),
    ("dbnomics", "Derivatives & Cash Flow Hedges for Forecasted Inventory Purchases (ASC 815). On October 1, 2026, "
                 "Horizon Import hedges a forecast purchase of copper."),
    ("us_treasury", "A software company receives £120,000 upfront for a 12-month service contract. Explain how "
                    "revenue recognition may differ from cash receipt under IFRS 15."),
    ("govuk_tax_rate", "Income Tax Valuation Allowances for Net Operating Losses (ASC 740). At December 31, 2026, "
                       "Vanguard Biotech has a gross deferred tax asset of $800,000."),
])
def test_a_connector_is_not_called_for_a_question_it_cannot_answer(connector, query):
    assert not applies(connector, query)


async def test_fetch_live_data_calls_only_the_applicable_connectors(monkeypatch):
    called = []

    def stub(name):
        async def connector(query, *args, **kwargs):
            called.append(name)
            return None
        return connector
    for name in ("_find_bank_rate", "_find_policy_rate", "_find_cash_rate", "_find_best_series", "_find_two_series",
                 "_find_fred_series", "_find_abs_series", "_find_cso_series", "_find_treasury_figure", "_find_uk_tax_rate"):
        monkeypatch.setattr(live_data, name, stub(name))
    await live_data.fetch_live_data("What interest rate does HMRC charge on late VAT payments?")
    assert "_find_bank_rate" in called and not {"_find_policy_rate", "_find_cash_rate", "_find_best_series"} & set(called)
    called.clear()
    await live_data.fetch_live_data("What is the current policy rate?")
    assert {"_find_bank_rate", "_find_policy_rate", "_find_cash_rate"} <= set(called)


# 3. The no-source note -----------------------------------------------------------

def test_the_note_names_the_named_countrys_authority():
    note = official_sources_note("What is the standard GST rate in Singapore?")
    assert "iras.gov.sg" in note and "cbic" not in note.lower()
    assert "ato.gov.au" in official_sources_note("Australian GST rate and registration threshold?")
    ireland = official_sources_note("Ireland VAT standard rate?")
    assert "gov.ie" in ireland and "hmrc" not in ireland.lower()
    # No authority on the allowlist for the Isle of Man: the wrong one goes, the general default remains.
    assert "hmrc" not in official_sources_note("What exact VAT registration threshold applied in the Isle of Man in 1987?").lower()


def test_the_note_is_unchanged_where_the_country_was_already_right():
    # Only a wrong country's suggestion is replaced; nothing is added otherwise.
    default = official_sources_note("What is the US federal standard deduction for a single filer in 2026?")
    assert "ifrs.org" in default and "irs.gov" not in default
    assert "ons.gov.uk" not in official_sources_note("What is UK inflation?")
    assert "cbic-gst.gov.in" in official_sources_note("What is the GST rate on restaurant services in India?")
    assert "cbic-gst.gov.in" in official_sources_note("How is input tax credit claimed under GST?")   # no country named
    assert "gov.uk/hmrc" in official_sources_note("When is VAT registration required?")
    both = official_sources_note("Compare UK VAT and India GST registration thresholds")
    assert "gov.uk/hmrc" in both and "cbic-gst.gov.in" in both


def test_only_the_official_prefetch_reads_the_retrieval_requirements():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    readers = sorted(path.name for path in root.rglob("*.py")
                     if re.search(r"\.retrieval\b|getattr\([^)]*[\"']retrieval[\"']|retrieval_requirements|RetrievalRequirement",
                                  path.read_text()))
    # registry_shadow.py (S4) reads them only to log the registry's selection;
    # clarification_requirements.py asks for a country an official part needs.
    assert readers == ["clarification_requirements.py", "official_prefetch.py", "registry_shadow.py", "task_contract.py"]
