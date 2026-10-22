"""Reliability spec phases 1, 2 and 4 — scenario follow-ups, 22 Oct 2026.

Ten scenario follow-ups in one chat (tests/fixtures/reliability_20261022.json)
failed for the same structural reasons: earlier turns reached the model only
through a narrow phrase gate (RC1); naming a framework forced every sentence to
cite sources the library does not hold (RC2); a calculator shortcut blocked on
a supplied figure (RC4); and the supplied-context check misread a request to
write journal entries and quoted the oldest message (RC5).

Each original follow-up is tested with two paraphrases written for this suite,
so passing does not depend on the exact wording. No model is called: the
end-to-end cases capture the prompt a scripted model receives.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.conversation_resolver import (
    asks_something, is_scenario_only, resolve_conversation,
)
from app.orchestration.schemas import ConversationMessage
from app.orchestration.supplied_context import missing_in_supplied_context
from app.orchestration.verification_service import requires_authoritative_evidence
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "reliability_20261022.json").read_text())
CONVERSATION = FIXTURE["conversation"]
POSITION = {message["id"]: index for index, message in enumerate(CONVERSATION) if message.get("id")}
TEXT = {message["id"]: message["content"] for message in CONVERSATION if message.get("id")}
CASES = FIXTURE["cases"]
SCENARIOS = {case["scenario"] for case in CASES}


def _history(upto: int) -> list[ConversationMessage]:
    return [ConversationMessage(role=m["role"], content=m["content"]) for m in CONVERSATION[:upto]]


def _sent_history(upto: int) -> list[ConversationMessage]:
    """What the page sends with a request: at most the last 12 messages."""
    return _history(upto)[-12:]


def _resolve(query: str, upto: int):
    return resolve_conversation(query, _history(upto),
                                legacy_follow_up=service._looks_like_contextual_follow_up,
                                standalone=service._standalone_with_figures)


def _wordings():
    for case in CASES:
        yield pytest.param(case, TEXT[case["followup"]], id=f"{case['followup']}-original")
        for number, paraphrase in enumerate(case["paraphrases"], 1):
            yield pytest.param(case, paraphrase, id=f"{case['followup']}-paraphrase{number}")


# ── Phase 1: conversation resolution (RC1) ──────────────────────────────────

@pytest.mark.parametrize("case,query", list(_wordings()))
def test_a_scenario_follow_up_is_linked_to_its_own_scenario_only(case, query):
    resolution = _resolve(query, POSITION[case["followup"]])
    scenario = POSITION[case["scenario"]]
    others = {POSITION[name] for name in SCENARIOS} - {scenario}
    assert resolution.follows_up, resolution
    assert scenario in resolution.relevant_turns
    assert not others & set(resolution.relevant_turns), "an unrelated scenario was imported"
    assert TEXT[case["scenario"]] in resolution.scenario_text()


@pytest.mark.parametrize("scenario", sorted(SCENARIOS - {"apex-scenario"}))
def test_a_scenario_without_a_question_is_recognised_and_starts_fresh(scenario):
    assert is_scenario_only(TEXT[scenario])
    resolution = _resolve(TEXT[scenario], POSITION[scenario])
    assert not resolution.follows_up, f"{scenario} was attached to an earlier scenario"


def test_every_resolved_figure_is_traced_to_the_turn_that_supplied_it():
    case = next(c for c in CASES if c["followup"] == "titan-followup")
    resolution = _resolve(TEXT["titan-followup"], POSITION["titan-followup"])
    figures = {fact.text: fact.turn_index for fact in resolution.facts}
    assert figures["$800,000"] == POSITION[case["scenario"]] and figures["$195,000"] == POSITION[case["scenario"]]
    assert "$210,618" not in figures
    assert resolution.summary()["facts"] and "content" not in json.dumps(resolution.summary())


def test_a_topic_change_after_a_scenario_is_not_attached_to_it():
    resolution = _resolve("What is the current UK VAT registration threshold?", POSITION["payroll-followup"])
    assert not resolution.follows_up


def test_a_conjunction_that_is_not_a_reference_to_an_earlier_scenario():
    earlier = [{"role": "user", "content": "Revenue is £800,000 and cost of goods sold £490,000. Calculate gross profit."},
               {"role": "assistant", "content": "Gross profit is £310,000."}]
    question = ("A manufacturer recorded a £75,000 sale on 30 December. Identify the audit risk. "
                "Do not conclude that revenue is definitely misstated.")
    assert not resolve_conversation(question, earlier).follows_up


def test_a_new_self_contained_question_with_its_own_figures_stands_alone():
    resolution = _resolve("Revenue is $900,000 and cost of sales is $540,000. What is the gross margin?",
                          POSITION["options-followup"] + 2)
    assert not resolution.follows_up and resolution.history() == []


def test_the_first_message_has_nothing_to_resolve():
    assert resolve_conversation("Explain accrual accounting.", []).kind == "first_turn"


def test_a_question_inside_a_scenario_message_is_still_a_question():
    assert asks_something(TEXT["apex-scenario"]) and not is_scenario_only(TEXT["apex-scenario"])


# ── Phase 2: shortcut and reference bugs (RC4, RC5) ─────────────────────────

def test_a_supplied_depreciation_figure_does_not_trigger_a_depreciation_clarification():
    assert calculate_from_query(TEXT["deferred-scenario"]).status == "not_matched"


def test_a_real_depreciation_request_still_asks_for_what_is_missing():
    result = calculate_from_query("Calculate straight-line depreciation for a machine costing $50,000")
    assert result.status == "clarification_required" and "useful life" in result.message


@pytest.mark.parametrize("query", [
    "Calculate straight-line depreciation: cost $50,000, residual value $5,000, useful life 5 years",
    "Calculate straight-line depreciation for an asset costing $50,000 with a residual value of $5,000 "
    "and a useful life of 5 years",
])
def test_depreciation_reads_a_plainly_stated_cost(query):
    result = calculate_from_query(query)
    assert result.status == "success"
    assert any(output.value == 9000 for output in result.outputs)


@pytest.mark.parametrize("query", [TEXT["meridian-followup"]] + next(
    c for c in CASES if c["followup"] == "meridian-followup")["paraphrases"])
def test_a_request_to_write_journal_entries_is_not_a_reference_to_missing_entries(query):
    earlier = [TEXT["apex-scenario"], TEXT["meridian-scenario"]]
    assert missing_in_supplied_context(query, earlier) is None


def test_a_reference_to_existing_entries_is_still_checked_and_names_the_latest_message():
    found = missing_in_supplied_context("Show the original, incorrect, and correcting entries together.",
                                        ["Apex scenario text with $1,000 and $2,000.", "The company paid rent of £5,000."])
    assert found is not None and found.title.startswith("The company paid rent")


# ── Phase 4: evidence requirement by intent (RC2) ───────────────────────────

@pytest.mark.parametrize("case", CASES, ids=[c["followup"] for c in CASES])
def test_applying_a_framework_to_a_supplied_scenario_is_not_a_source_lookup(case):
    question = TEXT[case["followup"]]
    assert not requires_authoritative_evidence(question, context=f"{TEXT[case['scenario']]}\n\n{question}")


@pytest.mark.parametrize("question,context", [
    ("What is the current UK VAT registration threshold?", ""),
    ("Calculate PF and ESI for an employee earning ₹25,000 a month.", ""),
    ("When is the GSTR-3B due for October 2026?", ""),
    ("Under section 179, what is the deduction limit for 2026?", "Equipment cost $250,000 and $40,000."),
    ("What tax rate applies to this company's profit of $180,000?", "Profit is $180,000 and revenue $900,000."),
    # The deferred-tax question needs a rate from somewhere when none is given.
    (TEXT["deferred-followup"], "Pre-tax income $500,000; depreciation $120,000 versus $70,000."),
])
def test_rates_thresholds_deadlines_and_unsupplied_tax_rates_still_need_sources(question, context):
    assert requires_authoritative_evidence(question, context=f"{context}\n\n{question}")


# ── End to end: the scenario reaches the model, an unrelated one does not ──

def _capture_prompts(pipeline, monkeypatch):
    prompts: list[str] = []

    async def agentic(prompt, *args, **kwargs):
        prompts.append(prompt)
        return AgentOutcome(text="Goodwill = 800,000 + 195,000 - 750,000 = 245,000.")

    async def standard(*args, **kwargs):
        prompts.append(" ".join(str(a) for a in args if isinstance(a, str)))
        return "Goodwill = 800,000 + 195,000 - 750,000 = 245,000."

    pipeline.agent.side_effect = agentic
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", AsyncMock(side_effect=standard))
    return prompts


@pytest.mark.parametrize("query", [TEXT["titan-followup"]] + next(
    c for c in CASES if c["followup"] == "titan-followup")["paraphrases"])
async def test_the_follow_up_prompt_carries_its_scenario_and_no_other(pipeline, monkeypatch, query):
    prompts = _capture_prompts(pipeline, monkeypatch)
    await pipeline.ask(query, history=_sent_history(POSITION["titan-followup"]))
    assert prompts, "no model request was made"
    prompt = prompts[0]
    assert "$800,000" in prompt and "$195,000" in prompt and "$750,000" in prompt
    assert "$210,618" not in prompt and "$360,000" not in prompt


async def test_a_deferred_tax_follow_up_is_not_turned_into_a_depreciation_clarification(pipeline, monkeypatch):
    prompts = _capture_prompts(pipeline, monkeypatch)
    response, _ = await pipeline.ask(TEXT["deferred-followup"], history=_sent_history(POSITION["deferred-followup"]))
    assert response.outcome != "clarification_required"
    assert prompts and "$120,000" in prompts[0] and "21%" in prompts[0]
    assert "Citation rule: every sentence" not in prompts[0]
