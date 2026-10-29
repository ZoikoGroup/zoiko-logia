"""Stage 5: essential context survives history selection and fitting (27 Oct 2026).

Test definitions agreed before implementation:
~/kriton-backups/2026-10-27-remediation2/stage5-reproduction-and-test-definitions.md

Reproduced: for "…for that lease" after a 6-exchange lease conversation, the
request sent to the model held none of the user's essentials (United
Kingdom, IFRS 16, the year end, £30,000, 6%, the correction). The resolver
keeps only the latest exchange. Scripted model client: no live calls.
"""
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway import service as gateway
from app.domains.model_gateway.agent_budget import request_prompt_estimate
from app.domains.model_gateway.errors import ProviderRequestTooLarge
from app.orchestration.conversation import conversation_prompt
from app.orchestration.schemas import ConversationMessage as M
from tests.test_agent_loop import ScriptedClient, _call, _reply
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

_real_agent_completion = gateway.run_agentic_completion

CONTEXT = "We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."
LEASE = "We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 4 years."
CORRECTION = "Correction: the lease term is 5 years, not 4. Initial direct costs are £7,279.69."
LATER = ["Explain how the right-of-use asset is measured.", "What disclosures would the notes need?",
         "How does this differ from a short-term lease?"]
ESSENTIALS = ["United Kingdom", "IFRS 16", "year ending 31 December 2025", "£30,000", "6%", CORRECTION]
# A follow-up the model answers: since 28 Oct 2026 the lease calculator
# (calculations/lease.py) answers "Now calculate the lease liability … for that
# lease" itself, with no model prompt to inspect; that answer is checked in
# test_the_calculated_follow_up_uses_the_corrected_lease below.
FOLLOW_UP = "Now explain the IFRS 16 disclosures needed for that lease, using its figures."
CALCULATED_FOLLOW_UP = "Now calculate the lease liability, first-year interest and first-year depreciation for that lease."


async def test_the_calculated_follow_up_uses_the_corrected_lease(pipeline, monkeypatch):
    from app.core.config import get_settings
    from app.domains.model_gateway.agent import AgentOutcome
    monkeypatch.setattr(get_settings(), "AGENT_MAX_REQUEST_TOKENS", 8000)
    pipeline.answers(AgentOutcome(text="Answer."))
    response, _ = await pipeline.ask(CALCULATED_FOLLOW_UP, history=_chat(8000))
    values = {o.name: o.display_value for o in response.calculation.outputs} if response.calculation else {}
    assert response.route == "CALCULATION"
    assert values["lease_liability"] == "£126,370.91"                   # 5 years, not the superseded 4
    assert values["right_of_use_asset"] == "£133,650.60"                # + the corrected initial direct costs
    assert values["first_year_interest"] == "£7,582.25"


def _chat(reply_chars=3000, users=None):
    history = []
    for user in users or [CONTEXT, LEASE, CORRECTION, *LATER]:
        history += [M(role="user", content=user), M(role="assistant", content=("Detailed earlier answer. " * 400)[:reply_chars])]
    return history


async def _prompt(pipeline, monkeypatch, question, history):
    from app.core.config import get_settings
    from app.domains.model_gateway.agent import AgentOutcome
    monkeypatch.setattr(get_settings(), "AGENT_MAX_REQUEST_TOKENS", 8000)
    pipeline.answers(AgentOutcome(text="Answer."))
    response, _ = await pipeline.ask(question, history=history)
    sent = pipeline.agent.await_args
    return (sent.args[0], sent.kwargs) if sent else (None, response)


# --- should pass (failed on the code before Stage 5) ---

@pytest.mark.parametrize("reply_chars", [3000, 8000])
async def test_P1_P3_follow_up_carries_every_essential(pipeline, monkeypatch, reply_chars):
    prompt, _ = await _prompt(pipeline, monkeypatch, FOLLOW_UP, _chat(reply_chars))
    assert [item for item in ESSENTIALS if item not in prompt] == []


async def test_P2_correction_follows_what_it_corrects(pipeline, monkeypatch):
    prompt, _ = await _prompt(pipeline, monkeypatch, FOLLOW_UP, _chat())
    assert prompt.index(LEASE) < prompt.index(CORRECTION)


async def test_P3_long_replies_go_first_and_are_named(pipeline, monkeypatch):
    prompt, _ = await _prompt(pipeline, monkeypatch, FOLLOW_UP, _chat(8000))
    assert "Some earlier messages were omitted" in prompt
    assert prompt.count("Detailed earlier answer.") < 400 * 6


async def test_P4_every_call_fits_with_tool_rounds(pipeline, monkeypatch):
    prompt, kwargs = await _prompt(pipeline, monkeypatch, FOLLOW_UP, _chat(8000))
    replies = [_reply("", [_call("calculate", {"expression": f"30000 * {n + 1}", "label": f"step {n}"}, f"c{n}")])
               for n in range(3)] + [_reply("Lease liability £126,370.91.")] * 4
    client = ScriptedClient(replies)
    monkeypatch.setattr(gateway, "GroqAdapter", lambda: N(client=client))
    await _real_agent_completion(prompt, **{**kwargs, "authorize": None})
    assert len(client.requests) >= 4
    for request in client.requests:
        assert request_prompt_estimate(request["messages"], request.get("tools")) + request["max_completion_tokens"] <= 8000
        assert all(item in request["messages"][-1]["content"] or item in str(request["messages"]) for item in ESSENTIALS)


# --- should still hold ---

@pytest.mark.parametrize("question", ["What is the UK VAT registration threshold?",
                                      "Explain IFRS 15 revenue recognition."])
async def test_N1_N2_new_question_carries_no_lease_scenario(pipeline, monkeypatch, question):
    prompt, _ = await _prompt(pipeline, monkeypatch, question, _chat())
    if prompt is not None:
        assert "£30,000" not in prompt and CORRECTION not in prompt


async def test_N3_chat_without_essentials_is_unchanged():
    history = [M(role="user", content="Explain what a lease is."), M(role="assistant", content="A lease is a contract.")]
    assert conversation_prompt(history, max_chars=6000) == conversation_prompt(history, max_chars=6000,
                                                                               essential=())


def test_unrelated_scenario_figures_are_not_added():
    from app.orchestration.conversation import with_essential_context
    breakeven = "Separately: break-even for a product selling at £25 with variable cost £15 and fixed costs £50,000?"
    history = _chat(users=[CONTEXT, LEASE, CORRECTION, breakeven])
    kept = with_essential_context(FOLLOW_UP, history, history[-2:])
    contents = [message.content for message in kept]
    assert CONTEXT in contents and LEASE in contents and CORRECTION in contents
    assert contents.index(LEASE) < contents.index(CORRECTION)
    # The resolver's own choice is left as it is; nothing else unrelated is added.
    assert [c for c in contents if "break-even" in c] == [breakeven]


def test_another_scenarios_question_or_shared_word_is_not_added():
    # Found by the existing suite while implementing: one shared word
    # ("price") and an ASC 606 question about another contract were added
    # to a goodwill follow-up.
    from app.orchestration.conversation import with_essential_context
    apex = "Using the 5-step model under ASC 606, calculate the allocated transaction price for each obligation."
    lease = "Meridian enters a 5-year lease; payments $50,000; it has a purchase option."
    titan = "Titan Inc. acquires an 80% interest in Delta Corp. for $800,000 in cash."
    history = _chat(users=[apex, lease, titan])
    kept = with_essential_context("Work out the goodwill on this acquisition and the purchase price allocation.",
                                  history, history[-2:])
    assert [m.content for m in kept if m.role == "user"] == [titan]


def _schedules(count):
    # Distinct messages: identical ones are deliberately kept once.
    return [(f"Lease {n} schedule line: £30,000 payment due, discount rate 6%. " * 140)[:8000] for n in range(count)]


def test_N4_essentials_too_large_stop_instead_of_being_cut():
    users = _schedules(3)
    history = [message for user in users for message in (M(role="user", content=user), M(role="assistant", content="Noted."))]
    block = conversation_prompt(history, max_chars=0, essential=users)
    assert all(user in block for user in users)                 # kept whole, never shortened


async def test_N4_oversized_essentials_raise_the_request_size_error(monkeypatch):
    from app.domains.model_gateway.agent_budget import GenerationBudget
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8000)
    client = ScriptedClient([])
    users = _schedules(4)
    essential = conversation_prompt([M(role="user", content=user) for user in users], max_chars=0, essential=users)
    with pytest.raises(ProviderRequestTooLarge):
        await budget.create(client, seconds=1, model="m", messages=[{"role": "user", "content": essential}])
    assert not client.requests
