"""The 28 Oct 2026 accounting test round (12 scenarios) and the architecture
behind its fixes: the lease calculator, provider-failure recovery, message
intent (context statements and corrections) and direct official values.

Expectation corrected from the round: scenario 6 (break-even at £40, variable
£25, fixed £90,000) is 6,000 units, not 3,250. Scenarios 3 (Pillar Two start
date) and 10 (VAT threshold) depend on live retrieval and are not covered
offline. No model, database or network: provider responses are scripted.
"""
from decimal import Decimal
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration.calculation_service import validate_answer_calculations
from app.orchestration.calculations.engine import calculate_from_query, vat_amounts
from app.orchestration.calculations.lease import LeaseTerms, calculate_lease, lease_calculation, present_value
from app.orchestration.message_intent import CALCULATION, CONTEXT, CORRECTION, QUESTION, classify_message
from app.orchestration.schemas import ConversationMessage as M
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


def _out(result):
    return {o.name: o.display_value for o in result.outputs}


# ── The 12 scenarios ──────────────────────────────────────────────────────────

def test_s1_an_answer_saying_the_users_entry_does_not_balance_is_kept():
    answer = ("| Account | Debit (£) | Credit (£) |\n|---|---|---|\n| Right-of-use asset | 133,650.60 | |\n"
              "| Lease liability | | 126,370.91 |\n\nThe journal entry does not balance by £7,279.69.")
    assert [f for f in validate_answer_calculations(answer) if f.startswith("Journal")] == []


def test_s2_ifrs16_lease_with_cash_flows_is_calculated():
    result = lease_calculation("We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease "
                               "term 5 years. Show the IFRS 16 accounting for the lessee, including the cash flow "
                               "statement.")
    assert result.status == "success"
    assert _out(result)["lease_liability"] == "£126,370.91"
    assert _out(result)["first_year_depreciation"] == "£25,274.18"
    cash = next(note for note in result.notes if note.startswith("Cash flows"))
    assert "principal portion is a financing activity" in cash and "IAS 7" in cash


@pytest.mark.parametrize("question, expected", [
    ("Calculate straight-line depreciation on a machine costing £60,000 with residual value £6,000 over nine years.",
     {"annual_depreciation": "£6,000.00"}),                                                           # s4
    ("Calculate gross profit and margin: we generated £450,000 in revenue and cost of sales was £270,000.",
     {"gross_profit": "£180,000.00", "gross_margin": "40.00%"}),                                      # s5
    ("Under IFRS 15, revenue £1,200,000 and cost of sales £780,000. What is the gross profit and margin?",
     {"gross_profit": "£420,000.00", "gross_margin": "35.00%"}),                                      # s7
    ("What is the break-even point for a product selling at £50 with variable cost £30 and fixed costs £40,000?",
     {"contribution_per_unit": "£20.00"}),                                                            # s9c
])
def test_deterministic_scenarios(question, expected):
    outputs = _out(calculate_from_query(question))
    assert {key: outputs[key] for key in expected} == expected


def test_s6_break_even_sold_at_40_is_6000_units():
    result = calculate_from_query("What is the break-even point for a product sold at £40 with variable cost £25 and "
                                  "fixed costs £90,000?")
    assert {o.name: o.value for o in result.outputs}["break_even_units"] == 6000


def test_s8_vat_payable_and_the_what_if():
    first = vat_amounts("UK company, VAT at 20%, all standard-rated, figures exclude VAT: sales £100,000, purchases "
                        "£50,000. Calculate VAT payable.")
    second = vat_amounts("UK company, VAT at 20%, all standard-rated, figures exclude VAT: sales £100,000, purchases "
                         "£60,000. Calculate VAT payable.")
    assert [o.display_value for o in first.outputs][-1] == "£10,000.00"
    assert [o.display_value for o in second.outputs][-1] == "£8,000.00"


async def test_s9a_and_s12_context_statements_are_acknowledged_without_a_model(pipeline):
    for text in ["We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025.",
                 "The company recognised revenue of £500,000 for the year.\nManagement believes the receivables are "
                 "fully recoverable.\nThe auditor has not yet reviewed the bad debt provision."]:
        pipeline.agent.reset_mock()
        response, _ = await pipeline.ask(text)
        assert response.outcome == "acknowledged"
        assert response.next_action.message.startswith("Noted")
        assert not pipeline.agent.await_args


async def test_s9b_a_lease_statement_is_acknowledged_with_its_figures(pipeline):
    response, _ = await pipeline.ask("We lease equipment: annual payments of £20,000 in arrears, discount rate 5%, "
                                     "lease term 4 years.")
    message = response.next_action.message
    assert response.outcome == "acknowledged" and all(f in message for f in ("£20,000", "5%", "4 years"))


async def test_s9d_that_lease_is_calculated_from_the_earlier_lease_not_the_break_even(pipeline):
    history = [
        M(role="user", content="We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."),
        M(role="assistant", content="Noted."),
        M(role="user", content="We lease equipment: annual payments of £20,000 in arrears, discount rate 5%, lease term 4 years."),
        M(role="assistant", content="Noted."),
        M(role="user", content="Separately: what is the break-even point for a product selling at £50 with variable "
                               "cost £30 and fixed costs £40,000?"),
        M(role="assistant", content="2,000 units."),
    ]
    response, _ = await pipeline.ask("Now calculate the lease liability and first-year interest for that lease.",
                                     history=history)
    values = _out(response.calculation)
    assert values["lease_liability"] == "£70,919.01" and values["first_year_interest"] == "£3,545.95"
    assert "contribution_per_unit" not in values


# ── The lease calculator ──────────────────────────────────────────────────────

def _terms(**changes):
    base = dict(payment=Decimal(50000), currency="USD", periods_per_year=1, years=Decimal(5),
                annual_rate=Decimal(6), timing="arrears")
    return LeaseTerms(**{**base, **changes})


def test_present_value_matches_the_independent_formula():
    expected = Decimal(50000) * (1 - Decimal("1.06") ** -5) / Decimal("0.06")
    assert abs(present_value(_terms()) - expected) < Decimal("1e-10")


def test_payments_in_advance_include_the_first_payment_undiscounted():
    arrears, advance = present_value(_terms()), present_value(_terms(timing="advance"))
    assert abs(advance - arrears * Decimal("1.06")) < Decimal("1e-10")


def test_the_schedule_closes_at_zero_and_principal_sums_to_the_liability():
    result = calculate_lease(_terms(framework="IFRS 16"))
    rows = result.tables[0]["rows"]
    assert rows[-1][-1] == "$0.00"
    assert len(rows) == 5 and result.verification_status == "passed"


def test_asc842_operating_lease_has_a_single_straight_line_cost():
    result = calculate_lease(_terms(framework="ASC 842", classification="operating"))
    assert _out(result)["annual_lease_cost"] == "$50,000.00"
    assert "first_year_depreciation" not in _out(result)
    assert any("operating activities" in note for note in result.notes)


def test_ifrs16_and_asc842_finance_cash_flows_differ_from_operating():
    finance = calculate_lease(_terms(framework="ASC 842", classification="finance"))
    assert any("interest portion is an operating activity" in note for note in finance.notes)


def test_quarterly_payments_use_the_periodic_rate():
    result = calculate_lease(_terms(periods_per_year=4, payment=Decimal(12500), years=Decimal(2)))
    rate = Decimal("0.015")
    assert abs(result.outputs[0].value - Decimal(12500) * (1 - (1 + rate) ** -8) / rate) < Decimal("1e-10")
    assert len(result.tables[0]["rows"]) == 8


def test_initial_direct_costs_and_incentives_adjust_only_the_asset():
    result = calculate_lease(_terms(initial_direct_costs=Decimal(2000), incentives=Decimal(500)))
    assert result.outputs[1].value - result.outputs[0].value == Decimal(1500)


@pytest.mark.parametrize("text, missing", [
    ("Calculate the lease liability: payments of £10,000 at 5% for 3 years.", "in advance"),
    ("Calculate the lease liability: payments of £10,000 in arrears for 3 years.", "discount rate"),
    ("Calculate the lease liability: payments of £10,000 in arrears at 5%.", "lease term"),
])
def test_a_missing_input_is_asked_for_not_assumed(text, missing):
    result = lease_calculation(text)
    assert result.status == "clarification_required" and missing in result.message


@pytest.mark.parametrize("text", [
    "What is a lease under IFRS 16?",
    "Calculate the lease liability: payments of £10,000 in arrears at 5% for 3 years with a purchase option of £2,000.",
    "Calculate the lease liability with variable payments of £10,000 in arrears at 5% for 3 years.",
])
def test_conceptual_or_unmodelled_leases_are_left_to_the_model(text):
    assert lease_calculation(text) is None


def test_lease_schedule_rows_count_as_verified_figures():
    from app.orchestration.verification_service import calculated_figures
    result = calculate_lease(_terms(currency="GBP", payment=Decimal(30000)))
    assert "28301.89" in {key for key in calculated_figures(result).results}


# ── Provider failure recovery ─────────────────────────────────────────────────

class _Rejected(Exception):
    def __init__(self, code="tool_use_failed", message="Tool choice is none, but model called a tool", status=400):
        super().__init__(message)
        self.status_code, self.body = status, {"error": {"code": code, "message": message}}


def _reply(content="", tool_calls=None):
    return N(choices=[N(message=N(content=content, tool_calls=tool_calls), finish_reason="stop")],
             usage=N(total_tokens=10))


class _Client:
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []
        self.chat = N(completions=N(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _adapter(steps):
    from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = _Client(steps)
    return adapter


_BAD_CHART = N(id="c1", function=N(name="render_chart",
                                   arguments='{"type": "waterfall", "series": [{"name": "x", "data": [1, 2]}]}'))


async def test_a_failed_chart_then_a_rejected_turn_still_answers_in_text():
    adapter = _adapter([_reply(tool_calls=[_BAD_CHART]), _Rejected(), _reply("Lease liability £126,370.91.")])
    text = await adapter.complete("Show the lease accounting with a waterfall chart.")
    assert text == "Lease liability £126,370.91."
    retry = adapter.client.requests[-1]
    assert "tools" not in retry and "plain text only" in retry["messages"][-1]["content"]
    assert retry["messages"][1]["content"] == "Show the lease accounting with a waterfall chart."   # evidence kept


async def test_an_unclassified_400_is_retried_once_only():
    adapter = _adapter([_Rejected(code="invalid_request_error", message="bad"), _Rejected(code="x", message="bad")])
    text = await adapter.complete("question")
    assert text.startswith("[Error connecting to Groq API")
    assert len(adapter.client.requests) == 2


@pytest.mark.parametrize("permanent", [_Rejected(code="", message="", status=401), _Rejected(code="", message="", status=413)])
async def test_permanent_failures_are_not_retried(permanent):
    from app.domains.model_gateway.errors import ProviderRequestRejected
    adapter = _adapter([permanent])
    with pytest.raises(ProviderRequestRejected):
        await adapter.complete("question")
    assert len(adapter.client.requests) == 1


async def test_the_agent_answers_without_tools_after_a_rejected_step():
    from tests.test_agent_loop import ScriptedClient, _registry, _run

    class _Then(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            step = self.replies.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

    client = _Then([_Rejected(code="invalid_request_error", message="tool call failed"), _reply("Final from evidence.")])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Final from evidence." and outcome.stop_reason == "provider_error"
    assert client.requests[-1].get("tool_choice") == "none"


# ── Message intent ────────────────────────────────────────────────────────────

LEASE = M(role="user", content="We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 4 years.")


@pytest.mark.parametrize("text, history, kind", [
    ("What is the UK VAT registration threshold?", [], QUESTION),
    ("Explain IFRS 16.", [], QUESTION),
    ("Calculate VAT on £500 at 20%.", [], CALCULATION),
    ("bought machine 24000 gbp lasts 6 years no resale value straight line depreciation yearly and monthly how much",
     [], CALCULATION),
    ("We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025.", [], CONTEXT),
    ("Our revenue is £500,000 and cost of sales £300,000.", [], CONTEXT),
    ("the lease term is 5 years, not 4.", [LEASE], CORRECTION),
])
def test_message_kinds(text, history, kind):
    assert classify_message(text, history) == kind


async def test_a_reply_to_a_clarification_is_not_treated_as_context(pipeline):
    response, _ = await pipeline.ask("UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. "
                                     "Calculate VAT payable.")
    assert response.outcome == "clarification_required"
    assert not response.next_action.message.startswith("Noted")


# ── Direct official values ────────────────────────────────────────────────────

def _bank_rate():
    from app.orchestration.evidence import EvidenceModel, Observation
    return EvidenceModel(subject="UK Bank Rate", provider="Bank of England", series_id="IUDBEDR", units=["%"],
                         observations=[Observation(dimension=d, value=v) for d, v in [
                             ("2025-10-28", 4.0), ("2025-12-17", 4.0), ("2025-12-18", 3.75), ("2026-10-26", 3.75)]])


def test_a_current_value_question_gets_the_value_its_date_and_the_source():
    from app.orchestration.service import _grounded_domain_fallback
    text = _grounded_domain_fallback("What is the current UK Bank Rate?", _bank_rate(), series_ref="REF-1")
    assert text.startswith("The current UK Bank Rate is 3.75%")
    assert "since 2025-12-18" in text and "[REF-1]" in text and "Bank of England series IUDBEDR" in text
    assert "observations" not in text and "minimum" not in text


def test_a_trend_question_still_gets_the_series():
    from app.orchestration.service import _grounded_domain_fallback
    text = _grounded_domain_fallback("How has the UK Bank Rate changed over the last year?", _bank_rate(),
                                     series_ref="REF-1")
    assert "observations" in text


def test_the_series_reference_is_found_by_its_source():
    from app.orchestration.service import _series_ref
    citations = [N(ref_id="REF-1", title="GOV.UK VAT", url="https://gov.uk/vat", evidence_preview=""),
                 N(ref_id="REF-2", title="Bank of England Bank Rate (IUDBEDR)", url="https://boe", evidence_preview="")]
    assert _series_ref(citations, _bank_rate()) == "REF-2"


# ── Found by the evaluation-set comparison while implementing ────────────────

@pytest.mark.parametrize("text", [
    "Draw a pie chart of our profit: Q1 £20,000, Q2 -£5,000, Q3 £12,000.",
    "Convert £10,000 to euros at today's exchange rate.",
    "Pass the journal entry for depreciation of ₹50,000 on machinery.",
    "Diagram the UK VAT registration decision: turnover over £90,000 in 12 months → must register.",
    "Start a new chat: Increase those expenses by 10% and recalculate.",
    "Pie chart of marketing budget: digital £45,000, print £15,000, events £25,000, PR £15,000",
])
def test_instructions_without_a_question_mark_are_not_context(text):
    assert classify_message(text) not in (CONTEXT, CORRECTION)


@pytest.mark.parametrize("rate_text", ["a 6% discount rate", "discount rate 6%", "at 6%", "6% incremental borrowing rate"])
def test_the_rate_is_read_in_its_usual_phrasings(rate_text):
    result = lease_calculation(f"Calculate the lease liability for annual payments of $50,000 in arrears for 5 years "
                               f"with {rate_text}.")
    assert _out(result)["lease_liability"] == "$210,618.19"


def test_a_numbered_task_list_is_a_request_and_a_negated_option_is_not_a_feature():
    result = lease_calculation("On January 1, 2026, a lessee leases machinery for 5 years with no renewal options. "
                               "Annual lease payments are $90,000 due at the start of each year. The rate implicit "
                               "in the lease is 8%. It is a finance lease under ASC 842. 1. Initial ROU asset and "
                               "lease liability. 2. 2026 interest expense and ROU amortisation.")
    assert _out(result)["lease_liability"] == "$388,091.42"


def test_a_stated_present_value_that_disagrees_with_the_rate_is_named():
    result = lease_calculation("Annual lease payments are $90,000 due at the start of each year for 5 years under "
                               "ASC 842. The discount rate is 8%. The present value of the remaining 4 annuity "
                               "payments at 8% is $298,991. 1. Initial ROU asset and lease liability. 2. Interest.")
    assert result.notes[0].startswith("Check the stated present value: you gave $298,991.00")
    assert "$298,091.42" in result.notes[0]
