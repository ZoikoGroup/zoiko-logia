"""Input requirements before answering (clarification_requirements.py), through
the real ask_kriton pipeline with a scripted model (3 Nov 2026).

Before: 4 of 18 incomplete requests were asked about; the rest went to the
model, which guessed. Each incomplete request must be asked about, each
complete one must not, and a reply sent as the frontend sends it (reply_to +
previous_query + history) must complete the original request without the
question being asked again."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.schemas import AskKritonRequest, ConversationMessage
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


async def _ask(pipeline, **fields):
    pipeline.agent.reset_mock()
    pipeline.answers(AgentOutcome(text="MODEL ANSWER PLACEHOLDER."))
    return await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                    request=AskKritonRequest(**fields))


def _question(response) -> str:
    return (response.next_action.message if response.next_action else "") or ""


INCOMPLETE = [
    ("What is the VAT registration threshold?", "Which country"),
    ("What is the corporate income tax rate?", "Which country"),
    ("When is my VAT return due?", "Which country"),
    ("What is the standard deduction for this year?", "Which country"),
    ("What are the payroll filing deadlines?", "Which country"),
    ("Do I need to charge sales tax on software?", "Which country"),
    ("What is the minimum wage?", "Which country"),
    ("Calculate the GST on my invoice.", "the amount"),
    ("How much income tax will I pay on a salary of 60,000?", "country"),
    ("Calculate straight-line depreciation on a machine costing £50,000.", "useful life"),
    ("Calculate the lease liability for annual payments of £10,000 over 5 years.", "discount rate"),
    ("What is the gross margin?", "revenue"),
    ("Record the journal entry for the sale.", "transaction details"),
    ("Is this misstatement material?", "materiality level"),
    ("Calculate overall materiality for our audit.", "benchmark"),
    ("Calculate the monthly loan repayment.", "the loan amount, the interest rate and the term"),
    ("What is the NPV of this project?", "cash flows"),
    ("Calculate the loan repayment on £200,000 over 25 years.", "interest rate"),
    ("Calculate the loan repayment on £200,000 at 5% over 25 years.", "monthly or annual"),
]


@pytest.mark.parametrize("query, asks_for", INCOMPLETE)
async def test_an_incomplete_request_is_asked_about(pipeline, query, asks_for):
    response = await _ask(pipeline, query=query)
    assert response.outcome == "clarification_required", (response.outcome, (response.answer.text if response.answer else "")[:120])
    assert asks_for in _question(response)
    pipeline.agent.assert_not_awaited()


COMPLETE = [
    ("Calculate straight-line depreciation: cost £40,000, residual value £4,000, useful life 8 years.", {}),
    ("What is the UK VAT registration threshold?", {}),
    ("Explain IFRS 16 lease accounting for lessees.", {}),
    ("Calculate VAT at 20% on £1,000 excluding VAT.", {}),
    ("What is materiality in auditing?", {}),
    ("What is the GST rate in Singapore?", {}),
    ("Calculate the lease liability: annual payments of £10,000 in arrears, discount rate 5%, lease term 5 years.", {}),
    ("Explain the going concern assumption.", {}),
    ("Explain how VAT works.", {}),
    ("What is VAT?", {}),
    ("What is the UK minimum wage?", {}),
    ("What is the PAYE threshold?", {}),
    ("What is the GST rate in Australia?", {}),
    ("Is GST payable on exports from India?", {}),
    ("What are the five steps of IFRS 15?", {}),
    ("How is straight-line depreciation calculated?", {}),
    ("What is the difference between overall and performance materiality?", {}),
    ("Calculate the monthly loan repayment on £200,000 at 5% over 25 years.", {}),
    ("Sales were £150,000, including VAT at 20%. Calculate sales excluding VAT and the VAT amount.", {}),
    # The country is implied by an authority, a currency or a scheme.
    ("What is the current RBA cash rate?", {}),
    ("What is the ECB main refinancing rate?", {}),
    ("What penalty does IRAS impose for late GST filing?", {}),
    ("What is the turnover limit to join the VAT Flat Rate Scheme?", {}),
    # Terms verified on HMRC and CBIC pages on 3 Nov 2026 (registry/country_terms.json).
    ("When must a business leave the VAT Cash Accounting Scheme?", {}),
    ("How many VAT returns do I submit under the Annual Accounting Scheme?", {}),
    ("How many penalty points trigger a VAT late submission penalty for monthly filers?", {}),
    ("What flat rate percentage does a limited cost business use?", {}),
    ("Does the VAT domestic reverse charge for construction apply when the customer is an end user?", {}),
    ("What is the GST registration threshold for service providers in Manipur?", {}),
    ("My sales in the last 12 months were £87,000 and this month I expect £6,000 more. Do I need to register for VAT?", {}),
    ("From what date do the new GST rates recommended at the 56th GST Council meeting apply?", {}),
    # A rate asked as "how much", a comparison, a method, a standard's own threshold.
    ("How much GST is charged on gold jewellery in India?", {}),
    ("How much GST is added to prices in New Zealand?", {}),
    ("What is the difference between VAT and GST as tax systems?", {}),
    ("What is the difference between a marginal tax rate and an effective tax rate?", {}),
    ("What is the effective interest rate method under IFRS 9?", {}),
    ("How do VAT registration thresholds work in general?", {}),
    ("At what income do UK Plan 2 student loan repayments start?", {}),
    # A process walk-through is not a request for an entry (QA case E02).
    ("Show how a draft journal entry becomes an approved posted journal entry.", {}),
    ("What is the NPV of £10,000 received in two years at an 8% discount rate?", {}),
    ("Segment reporting under ASC 280: an operating segment is reportable if it meets which quantitative threshold?", {}),
    # A country selected in the interface, or stated earlier in the case.
    ("What is the VAT registration threshold?", {"jurisdiction": "UK"}),
    ("What is the VAT registration threshold?", {"conversation_history": [
        ConversationMessage(role="user", content="We are a UK company."),
        ConversationMessage(role="assistant", content="Noted: UK company.")]}),
]


@pytest.mark.parametrize("query, extra", COMPLETE)
async def test_a_complete_request_is_not_asked_about(pipeline, query, extra):
    response = await _ask(pipeline, query=query, **extra)
    assert response.outcome != "clarification_required", _question(response)


DIALOGUES = [
    ("Calculate the monthly loan repayment.", ["£200,000 at 5% over 25 years."], "£1,169.18"),
    ("Calculate the loan repayment on £200,000 at 5% over 25 years.", ["Monthly."], "£1,169.18"),
    ("Calculate straight-line depreciation on a machine costing £50,000.",
     ["Residual value £5,000 and a useful life of 9 years."], "£5,000.00"),
    # The reply leaves whether ₹50,000 includes GST open: asked, then answered.
    ("Calculate the GST on my invoice.", ["The invoice is ₹50,000 and GST is 18%.", "It excludes GST."], "₹9,000.00"),
    ("What is the corporate income tax rate?", ["Singapore."], None),
    ("What is the VAT registration threshold?", ["The UK."], None),
    ("What is the minimum wage?", ["Australia."], None),
    ("Is this misstatement material?", ["The misstatement is £40,000 and overall materiality is £100,000."], None),
    ("Record the journal entry for the sale.", ["A credit sale of £5,000 plus VAT at 20% on 1 March."], None),
]


@pytest.mark.parametrize("first, replies, expected", DIALOGUES)
async def test_the_reply_completes_the_original_request(pipeline, first, replies, expected):
    response = await _ask(pipeline, query=first)
    assert response.outcome == "clarification_required"
    history = [ConversationMessage(role="user", content=first),
               ConversationMessage(role="assistant", content=_question(response))]
    chain = first
    for cycle, reply in enumerate(replies, start=1):
        previous = response
        response = await _ask(pipeline, query=reply, previous_query=chain, reply_to=previous.query_id,
                              clarification_cycle=cycle, conversation_history=history)
        history += [ConversationMessage(role="user", content=reply),
                    ConversationMessage(role="assistant", content=_question(response) or "ok")]
        chain = chain + "\n" + reply
    assert response.outcome != "clarification_required", _question(response)
    if expected is not None:
        assert expected in response.answer.text
    else:
        # Answered from the full request (the model, here scripted).
        pipeline.agent.assert_awaited()


def test_the_loan_repayment_is_the_annuity_payment():
    result = calculate_from_query("Calculate the monthly loan repayment on £200,000 at 5% over 25 years.")
    values = {o.name: o.display_value for o in result.outputs}
    assert values["monthly_repayment"] == "£1,169.18" and values["number_of_payments"] == "300"
    annual = calculate_from_query("Calculate the annual loan repayment on £10,000 at 6% over 5 years.")
    assert {o.name: o.display_value for o in annual.outputs}["annual_repayment"] == "£2,373.96"


def test_the_switch_turns_the_requirements_off(monkeypatch):
    from app.orchestration import clarification_requirements
    from app.orchestration.task_contract import build_task_contract
    question = "Calculate the monthly loan repayment."
    assert clarification_requirements.clarification(build_task_contract(question), task_query=question)
    monkeypatch.setenv("KRITON_CONTRACT_CLARIFICATION", "false")
    assert clarification_requirements.clarification(build_task_contract(question), task_query=question) is None


# Live retest (3 Nov 2026): a one-word reply crashed retrieval; "₹50,000, GST
# 18%" then "It excludes GST" was not calculated; a GST question was asked
# about "VAT".
async def test_a_two_letter_message_is_answered_not_crashed(pipeline):
    history = [ConversationMessage(role="user", content="What is the VAT registration threshold?"),
               ConversationMessage(role="assistant", content="The UK threshold is £90,000.")]
    response = await _ask(pipeline, query="UK", conversation_history=history)
    assert response.outcome != "error"


async def test_the_live_gst_reply_sequence_is_calculated(pipeline):
    first = "Calculate the GST on my invoice. Then reply: ₹50,000, GST 18%"
    one = await _ask(pipeline, query=first)
    assert one.outcome == "clarification_required" and "GST" in _question(one) and "VAT" not in _question(one)
    history = [ConversationMessage(role="user", content=first), ConversationMessage(role="assistant", content=_question(one))]
    two = await _ask(pipeline, query="It excludes GST", previous_query=first, reply_to=one.query_id,
                     clarification_cycle=1, conversation_history=history)
    assert "₹9,000.00" in two.answer.text


def test_two_amounts_are_not_guessed():
    assert not calculate_from_query("Calculate the GST on my invoice.\n₹50,000 and ₹20,000, GST 18%, excluding GST").matched


async def test_a_country_in_an_unrelated_earlier_question_does_not_answer_for_this_one(pipeline):
    history = [ConversationMessage(role="user", content="What is the current UK employer National Insurance contribution rate?"),
               ConversationMessage(role="assistant", content="The employer rate is 15%."),
               ConversationMessage(role="user", content="Calculate the monthly loan repayment on £200,000 at 5% over 25 years."),
               ConversationMessage(role="assistant", content="Monthly repayment £1,169.18.")]
    response = await _ask(pipeline, query="What is the VAT registration threshold?", conversation_history=history)
    assert response.outcome == "clarification_required" and "Which country" in _question(response)


# The live retest chat (3 Nov 2026, 18:41-18:43), as the frontend sent it
# (lib/clarification-reply.ts carries every turn since the last answer, less
# replies after which the same question was asked again).
GST_Q = "Calculate the GST on my invoice."


async def test_the_live_chat_a_new_request_is_not_read_as_a_reply(pipeline):
    history = [ConversationMessage(role="user", content=GST_Q),
               ConversationMessage(role="assistant", content="To work out the tax amount I need the amount."),
               ConversationMessage(role="user", content="₹50,000, GST 18%"),
               ConversationMessage(role="assistant", content="To work out the GST I need: (1) whether the amounts include GST")]
    loan = await _ask(pipeline, query="Calculate the monthly loan repayment.", previous_query=f"{GST_Q}\n₹50,000, GST 18%",
                      reply_to="qry-gst", clarification_cycle=4, conversation_history=history)
    assert loan.outcome == "clarification_required" and "loan amount" in _question(loan)
    history += [ConversationMessage(role="user", content="Calculate the monthly loan repayment."),
                ConversationMessage(role="assistant", content=_question(loan))]
    answer = await _ask(pipeline, query="£200,000 at 5% over 25 years",
                        previous_query=f"{GST_Q}\n₹50,000, GST 18%\nCalculate the monthly loan repayment.",
                        reply_to=loan.query_id, clarification_cycle=5, conversation_history=history)
    assert "£1,169.18" in answer.answer.text, _question(answer)


async def test_a_reply_that_answers_nothing_is_told_so(pipeline):
    first = await _ask(pipeline, query=f"{GST_Q}\n₹50,000, GST 18%")
    asked = _question(first)
    assert "excluding GST" in asked
    again = await _ask(pipeline, query="ok", previous_query=f"{GST_Q}\n₹50,000, GST 18%", reply_to=first.query_id,
                       clarification_cycle=2, conversation_history=[
                           ConversationMessage(role="user", content=f"{GST_Q}\n₹50,000, GST 18%"),
                           ConversationMessage(role="assistant", content=asked)])
    assert _question(again).startswith("I still need this before I can continue.")


def test_replies_are_not_requests():
    from app.orchestration.clarification_requirements import current_request_chain, is_own_request
    for reply in ("₹50,000, GST 18%", "It excludes GST", "UK", "Monthly.", "What if it is inclusive?",
                  "Residual value £5,000 and a useful life of 9 years.", "The invoice is ₹50,000 and GST is 18%."):
        assert not is_own_request(reply), reply
    assert current_request_chain(f"{GST_Q}\n₹50,000, GST 18%", "It excludes GST") == f"{GST_Q}\n₹50,000, GST 18%"
    assert current_request_chain(f"{GST_Q}\nCalculate the monthly loan repayment.", "£200,000 at 5% over 25 years") == \
        "Calculate the monthly loan repayment."
    assert current_request_chain(GST_Q, "Calculate the monthly loan repayment.") is None


# Live retest 3 (3 Nov 2026): "ok" repeated the question word for word, and a
# GST calculation was labelled VAT.
@pytest.mark.parametrize("reply, adds_nothing", [
    ('"ok".', True), ("ok", True), ("sure", True), ('"₹50,000, GST 18%"', True),
    ("excluding GST", False), ("UK", False), ("Monthly.", False), ("£200,000 at 5%", False),
])
def test_a_reply_that_adds_nothing(reply, adds_nothing):
    from app.orchestration.clarification_requirements import reply_adds_nothing
    assert reply_adds_nothing(reply, f"{GST_Q}\n₹50,000, GST 18%") is adds_nothing


async def test_the_live_ok_reply_says_it_still_needs_the_answer(pipeline):
    chain = f'"{GST_Q}"\n"₹50,000, GST 18%"'
    again = await _ask(pipeline, query='"ok".', previous_query=chain, reply_to="qry-gst", clarification_cycle=2,
                       conversation_history=[ConversationMessage(role="user", content=f'"{GST_Q}"'),
                                             ConversationMessage(role="user", content='"₹50,000, GST 18%"')])
    assert _question(again).startswith("I still need this before I can continue.") and "excluding GST" in _question(again)


async def test_a_gst_calculation_is_labelled_gst(pipeline):
    answer = await _ask(pipeline, query='"excluding GST"', previous_query=f'"{GST_Q}"\n"₹50,000, GST 18%"',
                        reply_to="qry-gst", clarification_cycle=2)
    assert "GST amount | ₹9,000.00" in answer.answer.text and "VAT" not in answer.answer.text


async def test_the_no_country_note_is_shown_once_and_names_gst(pipeline):
    answer = await _ask(pipeline, query='"excluding GST"', previous_query=f'"{GST_Q}"\n"₹50,000, GST 18%"',
                        reply_to="qry-gst", clarification_cycle=2)
    shown = "\n".join([answer.answer.text, *answer.answer.limitations])
    assert shown.count("names no country") == 1 and "VAT rules" not in shown
