"""The status a user sees must agree with what was actually released, through
the complete ask_kriton pipeline: a withheld figure or an unanswered part
cannot be presented as fully answered, and the audit record must say the
same as the page.

Only persistence, retrieval and the model are replaced; planning, routing,
the calculator, release checks and response assembly are the real ones.
Each case comes from live verification on 2026-10-16 (request ids below)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome, ToolCallRecord
from app.orchestration import learned_answers, review, service
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.schemas import AskKritonRequest


def page_status(response) -> str:
    """The badge frontend/app/ask-kriton/page.tsx (routeLabel) derives: the
    backend's completeness, else the limitation text."""
    limitations = (response.answer.limitations if response.answer else []) or []
    completeness = response.answer.completeness if response.answer else None
    if completeness == "none" or (completeness is None and any("No factual answer was verified" in i for i in limitations)):
        return "Not answered"
    if completeness == "partial" or (completeness is None and any("Incomplete answer" in i for i in limitations)):
        return "Partially answered"
    if response.outcome == "clarification_required":
        return "Clarification required"
    return "Answered"


@pytest.fixture
def pipeline(monkeypatch):
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    finalise = AsyncMock()
    monkeypatch.setattr(service, "_finalise_and_return", finalise)
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    # These cases exercise the agent path; it must not depend on a developer's
    # .env (CI has no KRITON_AGENT_MODE or GROQ_API_KEY, and refused them).
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    agent = AsyncMock(side_effect=AssertionError("this request must not reach the model"))
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", agent)
    # The release-correction rewrite is a model call too: no rewrite, so the
    # verify-and-prune path is what a test exercises.
    rewrite = AsyncMock(return_value="")
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", rewrite)

    async def ask(query: str, history=None):
        response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                            request=AskKritonRequest(query=query, conversation_history=history or []))
        audited = finalise.await_args.kwargs if finalise.await_args else {}
        return response, SimpleNamespace(outcome=audited.get("outcome"), completeness=audited.get("completeness"))

    def answers(outcome: AgentOutcome):
        agent.side_effect = None
        agent.return_value = outcome

    return SimpleNamespace(ask=ask, agent=agent, answers=answers, rewrite=rewrite)


# ── Failures 3 and 4: a withheld figure, named, and the same status everywhere ─

WITHHELD_QUESTION = "A supplier raised its price from £20,000 to £22,260. Explain what may have caused the increase."


async def test_a_withheld_figure_is_never_shown_as_fully_answered(pipeline):
    pipeline.answers(AgentOutcome(text="Verified working only.", unreconciled_figures=["£9,999"]))
    response, _ = await pipeline.ask(WITHHELD_QUESTION)
    assert response.outcome == "answered" and response.route == "LLM"
    assert page_status(response) == "Partially answered"


async def test_the_limitation_names_what_remains_unverified(pipeline):
    pipeline.answers(AgentOutcome(text="Verified working only.", unreconciled_figures=["£9,999", "13.4%"]))
    response, _ = await pipeline.ask(WITHHELD_QUESTION)
    limitation = next(item for item in response.answer.limitations if "withheld" in item)
    assert "these figures" in limitation and "£9,999, 13.4%" in limitation


async def test_more_than_five_unreconciled_figures_are_counted_not_dropped(pipeline):
    # A controlled reconciliation result, injected: the live model cannot be
    # made to produce one on demand.
    figures = ["£1,111", "£2,222", "33.3%", "£4,444", "£5,555", "£6,666", "£7,777"]
    pipeline.answers(AgentOutcome(text="Verified working only.", unreconciled_figures=figures))
    response, audited = await pipeline.ask(WITHHELD_QUESTION)
    limitation = next(item for item in response.answer.limitations if "withheld" in item)
    assert "£1,111, £2,222, 33.3%, £4,444, £5,555 and 2 more" in limitation
    assert "£6,666" not in limitation and "£7,777" not in limitation
    assert response.answer.completeness == audited.completeness == "partial"
    assert page_status(response) == "Partially answered"


async def test_a_repeated_unreconciled_figure_is_named_once(pipeline):
    pipeline.answers(AgentOutcome(text="Verified working only.", unreconciled_figures=["£2,260", "£2,260"]))
    response, audited = await pipeline.ask(WITHHELD_QUESTION)
    limitation = next(item for item in response.answer.limitations if "withheld" in item)
    assert "this figure" in limitation and limitation.count("£2,260") == 1
    assert audited.completeness == "partial"


async def test_the_audit_status_agrees_with_the_displayed_status(pipeline):
    pipeline.answers(AgentOutcome(text="Verified working only.", unreconciled_figures=["£9,999"]))
    response, audited = await pipeline.ask(WITHHELD_QUESTION)
    assert page_status(response) == "Partially answered"
    assert response.answer.completeness == audited.completeness == "partial"
    assert audited.outcome == response.outcome == "answered"   # unchanged for existing consumers


def test_the_answer_receipt_carries_the_same_completeness():
    from app.orchestration.router import answer_receipt
    from app.orchestration.schemas import ComposedAnswer
    result = SimpleNamespace(query_id="q", route="LLM", outcome="answered", safety=None,
                             answer=ComposedAnswer(text="x", completeness="partial"))
    run = SimpleNamespace(calculation_ids=[], citation_spans={}, state=SimpleNamespace(value="released"))
    assert answer_receipt(result, run)["completeness"] == "partial"


@pytest.mark.parametrize("limitations, expected", [
    ([], "complete"),
    (["Incomplete answer: some requested information could not be verified from the retrieved evidence."], "partial"),
    (["The retrieved evidence does not establish the requested answer. No factual answer was verified."], "none"),
])
def test_completeness_follows_the_limitations(limitations, expected):
    assert service.answer_completeness(limitations) == expected


async def test_a_correct_calculation_is_answered_and_verified_without_the_model(pipeline):
    response, audited = await pipeline.ask("A product costs £84 and sells for £126. Calculate the gross profit, gross margin and markup.")
    assert response.route == "CALCULATION" and audited.outcome == response.outcome == "answered"
    assert audited.completeness == response.answer.completeness == "complete"
    assert page_status(response) == "Answered"
    assert [o.display_value for o in response.calculation.outputs] == ["£42.00", "33.33%", "50.00%"]


# ── Failure 5: a factual part of a calculation request is never dropped ─────

MIXED = ("Revenue is £50,000 and cost of sales is £30,000. Calculate the gross margin, and tell me the "
         "ONS-published average gross margin for UK independent cafés in 2025.")


async def test_a_calculation_with_a_factual_part_is_not_answered_by_the_calculator_alone(pipeline):
    # qry-2be6ef6162c4: the margin was answered and the café average dropped
    # without a word, shown as "Answered".
    pipeline.answers(AgentOutcome(text=(
        "Gross margin = £20,000 ÷ £50,000 = 40%. The sources found do not state an ONS average gross margin "
        "for UK independent cafés in 2025.")))
    response, audited = await pipeline.ask(MIXED)
    prompt = pipeline.agent.await_args.args[0]
    assert "Verified application calculation" in prompt and "40.00%" in prompt   # the calculator's result goes in
    assert response.route == "LLM" and "40%" in response.answer.text
    assert page_status(response) == "Partially answered" and audited.completeness == "partial"


@pytest.mark.parametrize("query, part", [
    (MIXED, "tell me the ONS-published average gross margin for UK independent cafés in 2025."),
    ("Revenue £80,000, cost £50,000. Calculate the gross margin and explain why it matters.", "explain why it matters."),
    ("A product costs £84 and sells for £126. Calculate the gross profit, gross margin and markup.", ""),
    ("My revenue is ₹500,000 and expenses are ₹350,000. Calculate profit margin and show a pie chart.", ""),
    ("Fixed costs £50,000, price £25 per unit, variable cost £15 per unit. Break-even units?", ""),
])
def test_only_a_part_the_calculator_cannot_answer_is_detected(query, part):
    assert service.uncalculated_part(query) == part


# ── Failure 1: a negative VAT rate is invalid, never missing ───────────────

async def test_a_negative_vat_rate_is_rejected_through_the_pipeline(pipeline):
    response, audited = await pipeline.ask("Calculate VAT at −20% on £500.")
    assert audited.outcome == response.outcome == "clarification_required"
    assert response.calculation.error_code == "INVALID_PERCENTAGE"


@pytest.mark.parametrize("sign", ["-", "−", "–"])
def test_a_negative_vat_rate_after_the_amount_is_rejected_not_missing(sign):
    # qry-23e87efe1d4e: "VAT on £500 at −20%" was answered "please provide vat rate".
    result = calculate_from_query(f"Calculate VAT on £500 at {sign}20%.")
    assert result.error_code == "INVALID_PERCENTAGE" and result.message == "VAT rate cannot be negative."


async def test_a_negative_vat_rate_after_the_amount_is_rejected_through_the_pipeline(pipeline):
    response, audited = await pipeline.ask("Calculate VAT on £500 at −20%.")
    assert audited.outcome == "clarification_required"
    assert response.next_action.message == "VAT rate cannot be negative."


def test_another_percentage_is_never_taken_for_the_vat_rate():
    # Two percentages: the trailing-rate reading does not guess which is the rate.
    from app.orchestration.calculations.engine import _vat_rate_at
    assert _vat_rate_at("Calculate VAT on £500 after a 10% discount at 20%.") is None
    assert _vat_rate_at("Calculate VAT on £500 at 20%.").value == 20


# ── Failure 6: break-even, terse inputs, only what was asked ───────────────

def test_break_even_asking_only_for_units_gets_no_revenue_or_target_figures():
    result = calculate_from_query("Fixed costs are £50,000, the selling price is £25 per unit and variable cost is £15 "
                                  "per unit. What is the break-even point in units?")
    assert [o.name for o in result.outputs] == ["contribution_per_unit", "break_even_units"]
    assert result.outputs[1].value == 5000


def test_terse_break_even_units_question_is_calculated():
    # qry-c12be2c824e0: missed the calculator, answered with unrelated web citations.
    result = calculate_from_query("Fixed costs £50,000, price £25 per unit, variable cost £15 per unit. Break-even units?")
    assert result.status == "success"
    assert {i.name: i.value for i in result.inputs} == {"selling_price": 25, "variable_cost": 15, "fixed_costs": 50000}
    assert [o.name for o in result.outputs] == ["contribution_per_unit", "break_even_units"]


def test_a_conceptual_break_even_question_is_not_calculated():
    assert not calculate_from_query("Is break-even a useful concept?").matched


# ── Failure 7: a follow-up calculation is not replaced by an evidence gap ──

BREAK_EVEN_HISTORY = [
    {"role": "user", "content": "Fixed costs are £72,000, the selling price is £45 per unit and variable cost is £27 "
                                "per unit. What is the break-even point in units?"},
    {"role": "assistant", "content": "Contribution per unit = £45.00 − £27.00 = £18.00. Break-even units = "
                                     "£72,000.00 ÷ £18.00 = 4000.00 units."},
]


def test_a_follow_up_on_earlier_figures_plans_a_calculation_not_research():
    from app.orchestration.agent_plan import plan_request
    assert plan_request("Using the same figures, what profit would 6,000 units give?", history=True).tools == ("calculate",)
    # Rule questions in a conversation still research.
    assert "search_web" in plan_request("What was the VAT threshold in 2015?", history=True).tools


async def test_a_follow_up_calculation_is_not_replaced_by_an_evidence_gap(pipeline):
    # qry-e072804697aa: the agent calculated 6,000 × £18 − £72,000, was then
    # told to answer only from search results, and replaced the result with
    # "the sources found do not establish the answer".
    pipeline.answers(AgentOutcome(text="Profit = 6,000 × £18 − £72,000 = £36,000.",
                                  tool_calls=[ToolCallRecord(1, "calculate", "h", True, None, 5, 0)]))
    response, audited = await pipeline.ask("Using the same figures, what profit would 6,000 units give?", BREAK_EVEN_HISTORY)
    assert pipeline.agent.await_args.kwargs["require_evidence"] is False
    assert "£36,000" in response.answer.text
    assert audited.completeness == "complete" and response.answer.computed_from_question


# ── Failure 8: displayed citations are the ones the answer uses ────────────

def test_only_cited_sources_are_displayed():
    cites = [SimpleNamespace(ref_id=f"REF-{n}", provider=None) for n in range(1, 8)]
    shown = service.cited_only("Lower of cost and NRV [REF-1]. Written down to NRV [REF-2].", cites)
    assert [c.ref_id for c in shown] == ["REF-1", "REF-2"]


def test_an_answer_without_markers_keeps_only_provider_sources():
    # qry-28e5187219e5: a gross-margin answer citing nothing listed ten OECD papers.
    web = [SimpleNamespace(ref_id=f"REF-{n}", provider=None) for n in range(1, 4)]
    fx = SimpleNamespace(ref_id="REF-4", provider="Frankfurter")
    assert service.cited_only("£100 is €117.80 at today's rate.", web + [fx]) == [fx]


async def test_a_part_that_could_not_be_found_makes_the_answer_partial(pipeline):
    pipeline.answers(AgentOutcome(text=(
        # Verbatim from live qry-f82c24f05a36, which was still labelled complete.
        "Gross margin = £20,000 ÷ £50,000 = 40%. No ONS data on the average gross margin for independent "
        "cafés in the United Kingdom for 2025 could be retrieved from the available sources. To obtain the "
        "official figure, please consult the latest ONS publications or the ONS website.")))
    response, audited = await pipeline.ask(MIXED)
    assert response.answer.completeness == audited.completeness == "partial"
    assert response.answer.citations == []


async def test_an_invalid_rate_is_reported_as_invalid_not_missing(pipeline):
    response, _ = await pipeline.ask("Calculate VAT on £500 at \u221220%.")
    assert response.next_action.type == "calculation_input_invalid"
    response, _ = await pipeline.ask("Calculate the gross margin.")
    assert response.next_action is None or response.next_action.type != "calculation_input_invalid"
