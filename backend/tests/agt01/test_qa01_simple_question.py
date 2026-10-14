"""QA 1 — simple direct question: no tool or one retrieval; trace recorded."""
from agt01_support import reply, run


async def test_a_definition_is_answered_without_a_tool_loop():
    outcome, trace, requests = await run([reply("Accrual accounting records revenue when it is earned.")],
                                         question="What is accrual accounting?")
    assert outcome.stop_reason == "final_answer" and outcome.steps == 1
    assert trace == [] and outcome.tool_calls == [] and len(requests) == 1
