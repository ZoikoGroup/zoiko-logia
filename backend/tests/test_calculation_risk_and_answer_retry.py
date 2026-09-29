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
