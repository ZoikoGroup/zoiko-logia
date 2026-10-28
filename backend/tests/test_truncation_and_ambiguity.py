"""Standard-path truncation and ambiguous references (22 Oct 2026).

1. The standard path discarded a response cut off at the output limit,
   however much of it was finished ("Not answered — please try again"). The
   finished part is now shown, marked incomplete, never cached; an unfinished
   calculation or conclusion is never shown. The agent path is unchanged.
2. "that amount" with several earlier scenarios was resolved to the most
   recent one. Kriton now asks which, and the reply picks the scenario.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.domains.model_gateway.errors import ProviderResponseIncomplete
from app.domains.model_gateway.providers import groq_adapter
from app.orchestration import answer_cache, service
from app.orchestration.conversation_resolver import resolve_conversation
from app.orchestration.partial_output import STOPPED_NOTE, usable_partial
from app.orchestration.schemas import ConversationMessage
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

FINISHED = ("1. Allocation of the transaction price\n\n"
            "| Performance obligation | SSP | Allocated |\n|---|---|---|\n"
            "| Server | $120,000 | $108,000 |\n| Maintenance | $60,000 | $54,000 |\n| Support | $20,000 | $18,000 |\n\n"
            "The total of the allocated amounts equals the contract price ($108,000 + $54,000 + $18,000 = $180,000).\n\n")


# ── 1. What of a cut-off answer may be shown ────────────────────────────────

@pytest.mark.parametrize("cut, must_not_show", [
    ("Total revenue recognised in 2026 is $153,000. The deferred balance is 27,000 (\\", "27,000 (\\"),
    ("| Year | Interest | Balance |\n|---|---|---|\n| 1 | $12,637.09 | $173,255.28 |\n| 2 | $10,395.32 |", "$10,395.32"),
    ("Total = 108,000 + 27,000 +", "Total ="),
    ("3. Deferred revenue at year end is 27,000 (\\", "3."),
    ("## Deferred revenue\n", "## Deferred revenue"),
    ('```chart\n{"type": "bar", "data": [1, 2', "```"),
], ids=["mid-sentence", "half-table-row", "unfinished-equation", "numbered-item-cut", "dangling-heading",
        "open-chart-block"])
def test_only_finished_statements_of_a_cut_off_answer_are_shown(cut, must_not_show):
    shown = usable_partial(FINISHED + cut)
    assert shown.startswith("1. Allocation of the transaction price") and shown.endswith(STOPPED_NOTE)
    assert must_not_show not in shown.replace(STOPPED_NOTE, "")


def test_a_row_of_runaway_empty_cells_is_cut_back_to_the_table():
    journal = ("Payroll journal entry for the period covered by the payroll register, from the uploaded file.\n\n"
               "| Account | Debit | Credit |\n|---|---|---|\n| Wage (gross) expense | 86,850.00 | |\n"
               "| Employer National Insurance expense | 11,985.30 |" + " |" * 400 + "\n" + "| " * 50 + "|")
    shown = usable_partial(journal)
    assert "| Employer National Insurance expense | 11,985.30 |  |\n" in shown + "\n"
    assert "| | |" not in shown and shown.endswith(STOPPED_NOTE)


@pytest.mark.parametrize("cut", ["", "The allocated price for the server is", "## Results\nThe WACC is"])
def test_too_little_finished_text_is_not_shown(cut):
    assert usable_partial(cut) == ""


def _length_response(content, tool_calls=None):
    return SimpleNamespace(usage=SimpleNamespace(total_tokens=10), choices=[SimpleNamespace(
        finish_reason="length", message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def test_the_adapter_carries_the_cut_off_prose_and_not_a_cut_off_tool_call(monkeypatch):
    class _Completions:
        response = None

        async def create(self, **kwargs):
            return self.response

    monkeypatch.setenv("GROQ_API_KEY", "test")
    adapter = groq_adapter.GroqAdapter()
    completions = _Completions()
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    completions.response = _length_response("Finished sentence. Unfinished")
    with pytest.raises(ProviderResponseIncomplete) as raised:
        asyncio.run(adapter.complete("hi"))
    assert raised.value.partial_text == "Finished sentence. Unfinished"
    completions.response = _length_response("", tool_calls=[SimpleNamespace(id="t")])
    with pytest.raises(ProviderResponseIncomplete) as raised:
        asyncio.run(adapter.complete("hi"))
    assert raised.value.partial_text == ""


def _standard_path(pipeline, monkeypatch, failure):
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: False)
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", AsyncMock(side_effect=failure))
    stored = AsyncMock()
    monkeypatch.setattr(answer_cache, "put_answer", stored)
    return stored


QUESTION = ("On January 1, 2026, Nexus Corp sells a server ($120,000 SSP), maintenance ($60,000 SSP) and support "
            "($20,000 SSP) for $180,000. Allocate the transaction price under ASC 606.")


async def test_a_useful_cut_off_standard_answer_is_shown_as_partial(pipeline, monkeypatch):
    stored = _standard_path(pipeline, monkeypatch, ProviderResponseIncomplete(
        partial_text=FINISHED + "3. Deferred revenue at year end is 27,000 (\\"))
    response, audited = await pipeline.ask(QUESTION)
    assert response.answer is not None and response.outcome == "answered"
    assert response.answer.completeness == audited.completeness == "partial"
    # The finished part goes through the usual release checks (which may remove
    # figures computed without the calculator); the cut-off line never shows.
    assert "Allocation of the transaction price" in response.answer.text
    assert "27,000 (" not in response.answer.text and "\n3.\n" not in response.answer.text
    assert any("output limit" in item and "Only its finished part is shown" in item
               for item in response.answer.limitations)
    stored.assert_not_awaited()


async def test_an_unusable_cut_off_standard_answer_still_fails_safely(pipeline, monkeypatch):
    _standard_path(pipeline, monkeypatch, ProviderResponseIncomplete(partial_text="The allocated price is"))
    response, _ = await pipeline.ask(QUESTION)
    assert response.answer is None and response.outcome == "unavailable"
    assert response.next_action is not None and "output limit" in response.next_action.message


async def test_the_agent_path_keeps_its_own_partial_behaviour(pipeline):
    pipeline.agent.side_effect = None
    pipeline.agent.return_value = AgentOutcome(text=FINISHED, incomplete_reason="the model reached its output token limit")
    response, _ = await pipeline.ask(QUESTION)
    assert response.answer.completeness == "partial"
    assert any("output token limit" in item for item in response.answer.limitations)
    assert not any("Only its finished part is shown" in item for item in response.answer.limitations)


# ── 2. Ambiguous references ask instead of guessing ─────────────────────────

PROFIT = "Our company's taxable profit for 2026 is $180,000."
CONTRACT = "Nexus Corp sells a server for $120,000 and maintenance for $60,000 under one contract."
TAX = "Calculate the tax on that amount at 25%."


def _chat(*turns):
    history = []
    for text in turns:
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": "Answered."}]
    return history


def _resolve(question, history):
    return resolve_conversation(question, history, legacy_follow_up=service._looks_like_contextual_follow_up,
                                standalone=service._standalone_with_figures)


def test_that_amount_with_several_earlier_scenarios_asks_which():
    resolution = _resolve(TAX, _chat(PROFIT, CONTRACT))
    assert resolution.kind == "ambiguous" and not resolution.follows_up and resolution.history() == []
    assert "$180,000" in resolution.clarification and "$120,000" in resolution.clarification
    assert resolution.clarification.rstrip().endswith("?")


@pytest.mark.parametrize("reply, kept, left_out", [
    ("The $180,000 profit.", PROFIT, CONTRACT),
    ("The Nexus contract.", CONTRACT, PROFIT),
])
def test_the_reply_to_the_clarification_picks_one_scenario(reply, kept, left_out):
    asked = _resolve(TAX, _chat(PROFIT, CONTRACT))
    history = _chat(PROFIT, CONTRACT) + [{"role": "user", "content": TAX},
                                         {"role": "assistant", "content": asked.clarification}]
    resolution = _resolve(reply, history)
    assert resolution.follows_up and resolution.reasons[0] == "clarification_reply"
    assert kept in resolution.scenario_text() and TAX in resolution.scenario_text()
    assert left_out not in resolution.scenario_text()


@pytest.mark.parametrize("history", [_chat(PROFIT), _chat(CONTRACT, PROFIT)],
                         ids=["one-scenario", "previous-states-one-amount"])
def test_a_clear_reference_is_still_resolved_without_asking(history):
    resolution = _resolve(TAX, history)
    assert resolution.follows_up and PROFIT in resolution.scenario_text()


def test_naming_the_company_resolves_the_reference():
    resolution = _resolve("For Nexus, what is the tax on that amount?", _chat(PROFIT, CONTRACT))
    assert resolution.follows_up and resolution.reasons == ("named_party:Nexus",)


def test_an_unrelated_question_is_neither_ambiguous_nor_a_follow_up():
    resolution = _resolve("What is the current UK VAT registration threshold?", _chat(PROFIT, CONTRACT + " Allocate it."))
    assert resolution.kind == "standalone"


async def test_the_pipeline_asks_the_clarification_before_any_model_call(pipeline, monkeypatch):
    history = [ConversationMessage(role="user", content=PROFIT), ConversationMessage(role="assistant", content="Noted."),
               ConversationMessage(role="user", content=CONTRACT), ConversationMessage(role="assistant", content="Noted.")]
    response, _ = await pipeline.ask(TAX, history=history)
    assert response.outcome == "clarification_required"
    assert "Which amount or scenario do you mean?" in response.next_action.message
    pipeline.agent.assert_not_awaited()


# ── Review fixes (22 Oct 2026): the choice works in the app and is kept ─────
# The page replays only answers with text, so the clarification itself never
# comes back in the history: the choice is read from the user's own messages.

PAGE_HISTORY = [{"role": "user", "content": PROFIT}, {"role": "user", "content": CONTRACT},
                {"role": "user", "content": TAX}]


def _context(resolution):
    return " ".join(message["content"] for message in resolution.history())


@pytest.mark.parametrize("reply, kept, left_out", [
    ("The $180,000 profit.", PROFIT, CONTRACT),
    ("The Nexus contract.", CONTRACT, PROFIT),
    ("I mean the profit figure", PROFIT, CONTRACT),
])
def test_the_choice_is_recognised_from_the_history_the_page_sends(reply, kept, left_out):
    resolution = _resolve(reply, PAGE_HISTORY)
    assert resolution.reasons[0] == "clarification_reply"
    assert kept in _context(resolution) and TAX in _context(resolution) and left_out not in _context(resolution)


@pytest.mark.parametrize("follow_up", [
    "Now record the journal entry for that tax.",
    "And what would it be at 30%?",
    "Show the journal entry for it.",
])
def test_later_follow_ups_stay_on_the_chosen_scenario(follow_up):
    history = PAGE_HISTORY + [{"role": "user", "content": "The $180,000 profit."},
                              {"role": "assistant", "content": "Tax = $180,000 × 25% = $45,000."}]
    resolution = _resolve(follow_up, history)
    assert resolution.follows_up and PROFIT in _context(resolution) and CONTRACT not in _context(resolution)


def test_an_answered_clarification_is_not_passed_on():
    asked = _resolve(TAX, PAGE_HISTORY[:-1]).clarification
    history = PAGE_HISTORY + [{"role": "assistant", "content": asked}]
    context = _context(_resolve("The Nexus contract.", history))
    assert "Which amount or scenario" not in context and "$180,000" not in context


def test_a_new_full_question_after_an_ambiguous_one_is_not_taken_as_a_choice():
    resolution = _resolve("Calculate the depreciation on a machine costing $50,000 over 5 years with no residual value.",
                          PAGE_HISTORY)
    assert resolution.reasons[:1] != ("clarification_reply",)


@pytest.mark.parametrize("question, linked", [
    ("Record it in the general journal.", True),
    ("What is the journal entry for it?", True),
    ("Why is it important to reconcile bank statements monthly?", False),
])
def test_it_as_the_object_of_a_task_refers_back_and_a_dummy_it_does_not(question, linked):
    assert _resolve(question, _chat(PROFIT)).follows_up is linked


def test_a_phrase_follow_up_whose_chain_has_no_figures_keeps_the_whole_history():
    history = _chat("Show the UK CPI series for 2024.", "Explain what CPI measures.")
    resolution = _resolve("And what about 2023?", history)
    assert resolution.follows_up and resolution.whole_history and len(resolution.history()) == len(history)
