"""Second 22 Oct 2026 transcript: ten independent accounting/finance questions
in one chat. Six were cut off or not answered.

Root causes reproduced offline (no model calls):
  * the conversation resolver read "Task for the Bot:" as a shared company
    name and chained every scenario (test_reliability_conversation_resolution);
  * the agent path left GPT-OSS at medium reasoning inside the 4,096-token
    completion cap;
  * "applying US GAAP Lower of Cost or NRV rules" and "currently trading at
    $950" forced source-only answers for fully supplied questions;
  * tool calls written as text ('【calculate: expression=…}】') reached users;
  * AS 1105 (audit evidence) was cited for classifying control deficiencies.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.domains.model_gateway.agent_budget import GenerationBudget
from app.orchestration.accounting_concepts import correct_standard_references
from app.orchestration.calculation_service import needs_lookup
from app.orchestration.claim_verification import FIGURES_REMOVED_NOTE
from app.orchestration.verification_service import normalize_citations, requires_authoritative_evidence

LCNRV = ("Matrix Distributing uses the FIFO method. A: 1,200 units, cost $150, selling price $190, cost to sell $30. "
         "B: 800 units, cost $320, price $350, cost to sell $40. Determine the final inventory valuation for each "
         "category applying US GAAP Lower of Cost or NRV rules.")
WACC = ("Debt: 40,000 bonds, $1,000 par, 7% coupon, 15 years, currently trading at $950 per bond. Equity: 2,000,000 "
        "shares at $45, beta 1.3, risk-free rate 4.5%, market risk premium 6.0%. Tax rate 21%. Compute the WACC.")


class _Client:
    sent: dict = {}

    class chat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                _Client.sent = kwargs
                return SimpleNamespace(usage=SimpleNamespace(total_tokens=10), choices=[SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content="ok", tool_calls=None))])


@pytest.mark.parametrize("model", ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"])
def test_agent_calls_keep_the_provider_default_reasoning(model):
    """Low reasoning by default coincided with in-scope refusals in the 22 Oct
    live check; the default sends no reasoning_effort (provider medium)."""
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8_000)
    asyncio.run(budget.create(_Client, seconds=5, model=model, messages=[{"role": "user", "content": "hi"}]))
    assert "reasoning_effort" not in _Client.sent


def test_default_setting_leaves_reasoning_unset():
    from app.core.config import Settings
    assert Settings.model_fields["AGENT_REASONING_EFFORT"].default == ""


@pytest.mark.parametrize("model, expected", [("openai/gpt-oss-120b", "low"), ("openai/gpt-oss-20b", "low"),
                                             ("llama-3.3-70b-versatile", None)])
def test_low_reasoning_is_opt_in_and_gpt_oss_only(model, expected):
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8_000, reasoning_effort="low")
    asyncio.run(budget.create(_Client, seconds=5, model=model, messages=[{"role": "user", "content": "hi"}]))
    assert _Client.sent.get("reasoning_effort") == expected


def test_a_caller_value_wins_over_the_setting():
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8_000, reasoning_effort="low")
    asyncio.run(budget.create(_Client, seconds=5, model="openai/gpt-oss-120b", reasoning_effort="high",
                              messages=[{"role": "user", "content": "hi"}]))
    assert _Client.sent["reasoning_effort"] == "high"


@pytest.mark.parametrize("question", [LCNRV, WACC], ids=["lcnrv-rules", "wacc-currently-trading"])
def test_fully_supplied_questions_are_not_forced_into_source_only_answers(question):
    assert not requires_authoritative_evidence(question, context=question)


@pytest.mark.parametrize("question", [
    "What is the current corporate tax rate in the UK?",
    "What are the IFRS 16 rules for short-term leases?",
    "Under US GAAP, what are the rules for the current VAT threshold? Revenue $90,000 and $80,000.",
])
def test_authority_questions_still_need_sources(question):
    assert requires_authoritative_evidence(question, context=question)


def test_currently_trading_without_a_price_is_still_a_lookup():
    assert needs_lookup("Which stocks are currently trading above their 52-week high?")
    assert not needs_lookup("The bonds are currently trading at $950 per bond.")


@pytest.mark.parametrize("leaked, clean", [
    ('| Support | $18,000【calculate: expression="180000 * 20000 / 200000", label="Allocated price"}】 |',
     "| Support | $18,000 |"),
    ('| Liability | $210,618.19【calculate: expression="50000 * (1 - (1+0.06) ** -5) / 0.06", label="PV"} |',
     "| Liability | $210,618.19 |"),
    ('$54,000 ÷ 24 = $2,250【calculate: expression="54000 / 24", label="Monthly revenue"} for 12 months.',
     "$54,000 ÷ 24 = $2,250 for 12 months."),
])
def test_tool_calls_written_as_text_are_removed(leaked, clean):
    assert normalize_citations(leaked, set()) == clean


@pytest.mark.parametrize("prose", ["To calculate: the formula is price × units.", "The answer cites [REF-1] here."])
def test_ordinary_text_is_not_mistaken_for_a_tool_call(prose):
    assert normalize_citations(prose, {"REF-1"}) == prose


def test_audit_evidence_standard_cited_for_control_deficiencies_is_corrected():
    text, notes = correct_standard_references(
        "PCAOB AS 1105‑02 states that a significant deficiency is less severe than a material weakness.")
    assert text.startswith("PCAOB AS 2201 states") and notes
    assert correct_standard_references("Confirmations provide audit evidence under AS 1105.")[1] == []


def test_the_note_for_unchecked_figures_does_not_call_them_wrong():
    assert "did not match" not in FIGURES_REMOVED_NOTE and "could not be checked" in FIGURES_REMOVED_NOTE
