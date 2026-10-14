"""The backend plans before fetching (ZL-ENG-AGT-01 §02, §05.5, App. B4)."""
import pytest

from tests.test_agent_loop import ScriptedClient, _call, _registry, _reply, _run

from app.orchestration.agent_plan import plan_request

MARGINS = ("Company A: FY2024 operating profit 120,000 on revenue 1,000,000; FY2025 operating profit 150,000 "
           "on revenue 1,200,000. Compare the operating margins and chart the trend.")


@pytest.mark.parametrize("question", [
    "What is accrual accounting?", "Explain IFRS 16 lease accounting", "What is the UK VAT registration threshold?",
])
def test_simple_questions_skip_the_tool_loop(question):
    plan = plan_request(question)
    assert plan.mode == "simple" and plan.tools == () and plan.as_prompt() == ""


@pytest.mark.parametrize("question, tools", [
    (MARGINS, ("calculate", "render_chart")),
    ("Convert 10,000 GBP to EUR at the latest rate and show the rate date.", ("get_exchange_rate",)),
    ("Compare GDP growth for India and the UK over the last 5 years in a line chart.", ("get_economic_indicator", "render_chart")),
    ("What is the latest UK corporation tax rate and how much tax is due on profits of 300,000?",
     ("search_knowledge_base", "search_web", "calculate")),
])
def test_agent_questions_get_an_ordered_tool_plan(question, tools):
    plan = plan_request(question)
    assert plan.mode == "agent" and plan.tools == tools
    assert " → ".join(tools) in plan.as_prompt()


def test_a_follow_up_or_an_attached_document_is_never_treated_as_simple():
    assert plan_request("What is this?", history=True).mode == "agent"
    assert plan_request("What is this?", has_documents=True).mode == "agent"


async def test_a_tool_outside_the_plan_is_flagged_in_the_trace():
    from app.domains.model_gateway.agent import run_agent
    done = []

    async def on_done(record):
        done.append(record)

    client = ScriptedClient([_reply(tool_calls=[_call("lookup", {"key": "a"})]), _reply("done")])
    await run_agent(client, model="m", system_prompt="", user_prompt="q", registry=_registry([]),
                    granted_permissions=frozenset(), on_tool_done=on_done, planned_tools=("calculate",))
    assert done[0].planned is False


def test_a_new_question_in_an_existing_conversation_can_still_be_simple():
    """The service passes history only for real follow-ups (_looks_like_contextual_follow_up)."""
    from app.orchestration.service import _looks_like_contextual_follow_up
    assert not _looks_like_contextual_follow_up("What is accrual accounting?")
    assert plan_request("What is accrual accounting?", history=False).mode == "simple"


@pytest.mark.parametrize("question, expected", [
    ("File my VAT return for this quarter.", True), ("Can you file my payroll return?", True),
    ("Pay HMRC the VAT I owe", True), ("How do I file a VAT return?", False),
    ("What is the deadline to file a VAT return?", False),
])
def test_requests_to_act_are_told_kriton_will_not_act(question, expected):
    assert plan_request(question).write_request is expected


async def test_an_agent_that_answers_without_evidence_is_told_to_search_first():
    from app.domains.model_gateway.agent import run_agent
    client = ScriptedClient([_reply("Accrual accounting records revenue when earned."),
                             _reply(tool_calls=[_call("lookup", {"key": "accrual"})]),
                             _reply("Accrual accounting records revenue when earned [REF-1].")])
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="What is accrual accounting?",
                              registry=_registry([]), granted_permissions=frozenset(), require_evidence=True)
    assert "No evidence has been gathered" in client.requests[1]["messages"][-1]["content"]
    assert [r.tool for r in outcome.tool_calls] == ["lookup"] and outcome.sources


async def test_a_planned_search_is_tried_before_an_evidence_gap_answer():
    from app.domains.model_gateway.agent import run_agent
    client = ScriptedClient([_reply("The sources provided do not state this."),
                             _reply(tool_calls=[_call("lookup", {"key": "2015"})]),
                             _reply("The sources found do not establish the answer.")])
    registry = _registry([])  # the model then searches with the test "lookup" tool
    outcome = await run_agent(client, model="m", system_prompt="", user_prompt="Threshold in 2015?",
                              registry=registry, granted_permissions=frozenset(), planned_tools=("search_web",))
    assert "Before saying the sources do not establish this, call search_web" in client.requests[1]["messages"][-1]["content"]
    assert [r.tool for r in outcome.tool_calls] == ["lookup"]
