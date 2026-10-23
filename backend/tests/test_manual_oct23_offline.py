"""Offline regressions from the manual test of 23 Oct 2026 (port 3001).

Audit records (read-only) showed why four answers were replaced by bare
calculator steps: the arithmetic check read "1.09**2" as "1.092" (the bold
clean-up removed the power operator), and any one mismatch replaced the whole
explanation. Three more questions failed on routing: a supplied materiality
threshold, an audit scenario naming no standard, and supplied exchange rates.
No model calls.
"""
import pytest

from app.domains.model_gateway.agent import AgentLimits, AgentOutcome, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry
from app.orchestration import service
from app.orchestration.agent_plan import plan_request
from app.orchestration.calculation_service import needs_lookup, validate_answer_calculations, verifies_current_fact
from app.orchestration.fx_profit import latest_fx_requested
from app.orchestration.verification_service import requires_authoritative_evidence, supplies_a_professional_scenario
from tests.test_agent_loop import ScriptedClient, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)


# ── 1. The power operator is arithmetic, bold is not ──────────────────────────

@pytest.mark.parametrize("text", [
    "PV2 = 1.728/(1.09**2) = 1.454423",
    "PV4 = 2.322432/(1.09**4) = 1.645269",
    "PV = 60000/(1+0.08) + 60000/(1+0.08)**2 + (60000+1500000)/(1+0.08)**3 = 1,345,374.18",
])
def test_a_power_operator_is_not_read_as_bold(text):
    assert validate_answer_calculations(text) == []


@pytest.mark.parametrize("text", ["ROE = $468,000 ÷ $1,750,000 = **27.74 %**", "**Total** = 5 + 3 = 9"])
def test_a_wrong_bold_result_is_still_caught(text):
    assert validate_answer_calculations(text)


# ── 1b. One wrong line no longer replaces the whole explanation ───────────────

QUESTION = "Fixed costs are £780,000 and the contribution margin ratio is 55%. Explain break-even revenue."
EXPLAINED = ("Break-even revenue is the revenue at which contribution exactly covers fixed costs.\n"
             "Break-even revenue = £780,000 ÷ 0.55 = £1,560,000.\n"
             "Above that level each extra pound of revenue adds 55p of contribution to profit.")


async def _agent(text):
    client = ScriptedClient([_reply(text), _reply(text), _reply(text)])
    return await run_agent(client, model="m", system_prompt="sys", user_prompt=QUESTION, registry=ToolRegistry(),
                           granted_permissions=frozenset(), limits=AgentLimits(), stated_facts=QUESTION)


async def test_a_wrong_line_is_removed_and_the_explanation_kept():
    outcome = await _agent(EXPLAINED)
    assert "contribution exactly covers fixed costs" in outcome.text and "55p of contribution" in outcome.text
    assert "1,560,000" not in outcome.text and "generated explanation could not be verified" not in outcome.text
    assert outcome.disproved_notes and "1418181.82" in outcome.disproved_notes[0]


async def test_with_nothing_else_to_show_the_verified_working_is_used_as_before():
    outcome = await _agent("Break-even revenue = £780,000 ÷ 0.55 = £1,560,000.")
    assert "1,560,000" not in outcome.text
    assert "could not be verified" in outcome.text and not outcome.disproved_notes


async def test_the_reader_is_told_which_figure_was_wrong_and_its_correct_value(pipeline):
    pipeline.answers(AgentOutcome(text="Break-even revenue is where contribution covers fixed costs.",
                                  disproved_notes=["£1,560,000 (780,000 ÷ 0.55 equals 1418181.82)"]))
    response, _audited = await pipeline.ask(QUESTION)
    limitations = " ".join(response.answer.limitations)
    assert "did not match its own calculation" in limitations and "1418181.82" in limitations


# ── 2. A supplied materiality threshold is the user's figure ──────────────────

@pytest.mark.parametrize("text", [
    "The total materiality threshold for the entire financial audit is set at $750,000.",
    "Performance materiality limit is $500,000.",
    "The approval threshold of $3,000 applies to managers.",
])
def test_a_supplied_threshold_is_not_a_lookup(text):
    assert not needs_lookup(text)


def test_a_threshold_without_a_figure_is_still_a_lookup():
    assert needs_lookup("What is the current VAT registration threshold?")


# ── 3. Accounting and audit scenarios without a named standard ────────────────

INVENTORY = ("An audit team observes the inventory count on December 31, 2026. Lot X is valued at $85,000 "
             "(bill-and-hold, invoiced Dec 29). Lot Y is valued at $120,000, FOB Destination, arriving Dec 31. "
             "Lot Z is valued at $45,000, FOB Shipping Point, shipped Dec 30. Determine whether each lot is "
             "included in inventory and draft the adjusting journal entry.")


def test_an_audit_scenario_without_a_named_standard_is_professional_knowledge():
    assert supplies_a_professional_scenario(INVENTORY)
    assert not requires_authoritative_evidence(INVENTORY, INVENTORY)


async def test_it_is_answered_from_professional_knowledge_not_only_from_searches(pipeline):
    pipeline.answers(AgentOutcome(text="Lot Y is included; lots X and Z are excluded."))
    await pipeline.ask(INVENTORY)
    call = pipeline.agent.call_args
    assert call.kwargs["require_evidence"] is False
    assert service.PROFESSIONAL_APPLICATION_INSTRUCTION.strip() in call.args[0]


@pytest.mark.parametrize("question", [
    "Calculate simple interest on ₹10,00,000 at 6.5% per annum for 9 months.",
    "What is 15% of ₹2,00,000?",
])
def test_a_bare_calculation_is_not_labelled_general_explanation(question):
    assert not supplies_a_professional_scenario(question)


# ── 4. Supplied exchange rates are used, not replaced ─────────────────────────

SUPPLIED_RATES = [
    "Using a conversion rate of 1.10 USD per EUR, convert EUR 50,000 into USD. Do not retrieve a live rate.",
    "Translate USD 25,000 into INR using the supplied rate of ₹83.20 per USD. Show the calculation.",
    "The current spot rate is 5.00 BRL per $1 USD. Convert BRL 3,500,000 into USD and calculate the NPV at 10%.",
    "At an exchange rate of 1.25 USD per GBP, convert £40,000 into dollars.",
]


@pytest.mark.parametrize("question", SUPPLIED_RATES)
def test_a_supplied_rate_is_used_for_the_calculation(question):
    plan = plan_request(question)
    assert "calculate" in plan.tools and "get_exchange_rate" not in plan.tools
    assert not latest_fx_requested(question)
    assert not requires_authoritative_evidence(question, question)


@pytest.mark.parametrize("question", [
    "Convert EUR 50,000 to USD at today's rate.",
    "What is the current EUR/USD exchange rate?",
    "Convert 10,000 INR into USD at the latest rate",
    "Our UK company invoiced a German client €40,000. Convert it to pounds at the latest rate.",
])
def test_a_live_rate_request_still_fetches_it(question):
    assert "get_exchange_rate" in plan_request(question).tools and latest_fx_requested(question)


def test_converting_a_bond_into_shares_is_still_not_a_currency_conversion():
    assert "get_exchange_rate" not in plan_request(
        "Could an investor purchase the bond and convert it immediately at a profit?").tools


@pytest.mark.parametrize("question, indicator", [
    ("Reduce the nominal annual interest rate from 8% down to 4%. Calculate the gain on restructuring.", False),
    ("The inflation rate in the US is 2.5%, while the inflation rate in Brazil is 6.0%. Calculate the PPP rates.",
     False),
    ("Show US inflation and interest rate trend", True),
])
def test_a_supplied_interest_or_inflation_rate_is_not_an_indicator_lookup(question, indicator):
    assert ("get_economic_indicator" in plan_request(question).tools) is indicator


# ── 5. "Without checking" is an instruction, not a request ────────────────────

SIMPLE_INTEREST = ("Calculate simple interest on ₹10,00,000 at 6.5% per annum for 9 months. Show the formula, "
                   "substitution and result. Use the supplied rate without checking the current repo rate.")


def test_without_checking_the_current_rate_is_not_a_lookup():
    assert not verifies_current_fact(SIMPLE_INTEREST) and not needs_lookup(SIMPLE_INTEREST)
    assert not requires_authoritative_evidence(SIMPLE_INTEREST, SIMPLE_INTEREST)
    assert plan_request(SIMPLE_INTEREST).tools == ("calculate",)


@pytest.mark.parametrize("question", [
    "Check the current repo rate and compute interest on ₹10 lakh.",
    "Is the current repo rate 6.5%?",
    "What's the latest repo rate?",
])
def test_asking_for_the_current_rate_still_needs_a_source(question):
    assert requires_authoritative_evidence(question)


# ── Reasoning failures: answer keys (awaiting accountant review) ──────────────

from tests.answer_key import grade  # noqa: E402

SAVED_WRONG = {
    "pension": "Ending PBO = 4500000 + 280000 + 247500 - 190000 - 45000 = $4,792,500. Funded status ‑$222,500. "
               "Net periodic pension cost $285,500. Plan assets $4,570,000.",
    "segments": "10 % profit threshold = $1,020,000 × 0.10 = $102,000. Proportion = 0.9268 (≈ 92.68 %).",
    "tdr": "Total future cash flows: 1500000+3*60000 = 1680000. Loss on restructuring: 2160000-1345374.180765 = 814,625.82",
}


@pytest.mark.parametrize("name", ["pension", "segments", "tdr"])
def test_the_grader_flags_the_saved_wrong_answers(name):
    result = grade(SAVED_WRONG[name], name)
    assert result.contradictions and not result.passed


def test_a_correct_pension_answer_passes():
    assert grade("Net periodic pension cost $285,500; ending PBO $4,837,500; plan assets $4,570,000; "
                 "funded status −$267,500 (underfunded), a net pension liability.", "pension").passed
