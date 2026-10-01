"""A salary tax computation was escalated to human review, and a failed fast
answer model surfaced as "Kriton could not compose a response"."""
import asyncio

import pytest

from app.domains.model_gateway import service
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.orchestration.risk_llm import calibrate_calculation_risk


@pytest.mark.parametrize("query", [
    "Salary ₹18,00,000 under the new regime for FY 2025-26: calculate the income tax step by step.",
    "Calculate the income tax on a salary of 12 lakh under the new regime",
    "What is the VAT on a price of £1,250 at 20%?",
])
def test_calculation_on_stated_figures_is_not_high(query):
    assert calibrate_calculation_risk("HIGH", query) == "LOW"


@pytest.mark.parametrize("query", [
    "Should I opt for the old regime or new regime with salary 18,00,000?",
    "Am I required to register for VAT with turnover of £95,000?",
    "Calculate how to reduce my tax on 20,00,000 income",
    "Which regime is better for 15,00,000 salary? calculate both",
])
def test_decisions_stay_high(query):
    assert calibrate_calculation_risk("HIGH", query) == "HIGH"


def test_restricted_is_never_calibrated():
    assert calibrate_calculation_risk("RESTRICTED", "calculate 100 + 200") == "RESTRICTED"


def test_fast_model_failure_retries_with_main_model(monkeypatch):
    monkeypatch.setattr(service, "_select_adapter", lambda: GroqAdapter.__new__(GroqAdapter))
    models = []

    async def fake_complete(adapter, prompt, model):
        models.append(model)
        return "" if model else "Answer from the main model"

    monkeypatch.setattr(service, "_try_complete", fake_complete)
    assert asyncio.run(service._complete_with_fallback("question", "openai/gpt-oss-20b")) == "Answer from the main model"
    assert models == ["openai/gpt-oss-20b", None]


def test_fraction_working_is_checked():
    from app.orchestration.calculation_service import validate_answer_calculations
    wrong = r"\text{ROCE\%} = \frac{18,00,000}{1,00,00,000} \times 100 = 1.8\%"
    right = r"\text{ROCE\%} = \frac{18,00,000}{1,00,00,000} \times 100 = 18\%"
    assert validate_answer_calculations(wrong)
    assert validate_answer_calculations(right) == []
    assert validate_answer_calculations("Margin = 200,000 / 500,000 = 40%") == []


@pytest.mark.parametrize("text", [
    "I'm sorry, but I can't help with that.",
    "Sorry, I cannot assist with that request.",
])
def test_generic_refusal_is_recognised(text):
    from app.orchestration.service import _GENERIC_REFUSAL
    assert _GENERIC_REFUSAL.search(text)


def test_real_answers_are_not_mistaken_for_refusals():
    from app.orchestration.service import _GENERIC_REFUSAL
    assert not _GENERIC_REFUSAL.search("A provision is a liability of uncertain timing or amount.")


def test_partly_covered_questions_are_still_answered():
    from app.orchestration.websearch import WebSource, build_web_grounded_prompt
    prompt = build_web_grounded_prompt("q", [WebSource(title="t", url="https://x.gov", snippet="s")])
    assert "never reply only that the sources" in prompt


@pytest.mark.parametrize("query", [
    "Pass entries for the issue of 5,000 debentures of ₹100 each at a 5% discount, redeemable at par.",
    "Pass entries for salary of ₹50,000 paid after deducting TDS of ₹5,000 and PF of ₹3,000.",
    "What sales are needed for a profit of ₹6,00,000?",
])
def test_textbook_entries_and_targets_on_stated_figures_are_not_high(query):
    assert calibrate_calculation_risk("HIGH", query) == "LOW"


def test_journal_entry_for_own_decision_stays_high():
    assert calibrate_calculation_risk(
        "HIGH", "Should I pass a journal entry to write off ₹2,00,000 of my client's debtors?"
    ) == "HIGH"


def test_percent_inside_a_fraction_is_checked():
    from app.orchestration.calculation_service import validate_answer_calculations
    wrong = r"\frac{15\% + 22.5\% + 26.25\%}{3} = \frac{63.75\%}{3} = 21.75\%"
    assert validate_answer_calculations(wrong)
    assert validate_answer_calculations(wrong.replace("21.75", "21.25")) == []


def test_unbalanced_journal_entry_is_caught():
    from app.orchestration.calculation_service import validate_answer_calculations
    wrong = ("| Account | Dr (₹) | Cr (₹) |\n|---|---|---|\n| Share Capital | 10,000 | – |\n"
             "| Calls in Arrears | 3,000 | – |\n| Share Forfeiture | – | 7,000 |")
    assert validate_answer_calculations(wrong)
    right = wrong.replace("| Calls in Arrears | 3,000 | – |", "| Calls in Arrears | – | 3,000 |")
    assert validate_answer_calculations(right) == []


def test_journal_with_amount_columns_after_account_columns():
    from app.orchestration.calculation_service import validate_answer_calculations
    table = ("| Date | Account (Debit) | Amount (₹) | Account (Credit) | Amount (₹) |\n|---|---|---|---|---|\n"
             "| Purchase | Purchases | 58,800 | Mehta Traders | 58,800 |")
    assert validate_answer_calculations(table) == []


@pytest.mark.asyncio
async def test_comparison_keeps_countries_with_data(monkeypatch):
    from app.orchestration import dbnomics
    from app.orchestration.websearch import WebSource

    async def partial(code, label, countries):
        return [WebSource(title=c, url="https://data.worldbank.org", snippet="x") if c != "france" else None
                for c in countries]

    monkeypatch.setattr(dbnomics, "fetch_indicator_sources", partial)
    sources = await dbnomics.fetch_stats("Compare the tax-to-GDP ratio of India, United Kingdom, France and Brazil")
    titles = [s.title.lower() for s in sources]
    assert "india" in titles and "brazil" in titles
    assert any("no " in t and "france" in t for t in titles)
