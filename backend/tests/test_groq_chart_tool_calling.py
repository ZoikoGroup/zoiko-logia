"""GroqAdapter.complete() with the render_chart tool: the two-turn
function-calling round trip (model proposes -> backend validates and builds
the chart -> backend tells the model the outcome -> model writes final
prose), not the old "hope the model hand-writes correct JSON in its prose"
path."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.providers.groq_adapter import GroqAdapter


def _tool_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _response(content: str | None, tool_calls: list | None = None) -> SimpleNamespace:
    message = SimpleNamespace(
        role="assistant", content=content, tool_calls=tool_calls or None,
        model_dump=lambda: {"role": "assistant", "content": content, "tool_calls": tool_calls},
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _adapter() -> GroqAdapter:
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    return adapter


@pytest.mark.asyncio
async def test_no_tool_call_returns_content_unchanged():
    adapter = _adapter()
    adapter.client.chat.completions.create.return_value = _response("Plain answer, no chart needed.")

    result = await adapter.complete("What is IFRS 16?")

    assert result == "Plain answer, no chart needed."
    assert adapter.client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_valid_chart_tool_call_appends_backend_built_fence():
    adapter = _adapter()
    chart_args = {
        "type": "bar",
        "title": "GDP growth",
        "categories": ["2023", "2024"],
        "series": [{"name": "UK", "data": [0.27, 1.08]}],
    }
    first = _response(None, [_tool_call("call_1", "render_chart", chart_args)])
    second = _response("Here is the comparison you asked for.")
    adapter.client.chat.completions.create.side_effect = [first, second]

    result = await adapter.complete("Compare UK GDP growth")

    assert adapter.client.chat.completions.create.call_count == 2
    assert result.startswith("Here is the comparison you asked for.")
    assert "```chart" in result
    fence_json = json.loads(result.split("```chart\n", 1)[1].rsplit("\n```", 1)[0])
    assert fence_json["type"] == "bar"
    assert fence_json["categories"] == ["2023", "2024"]

    # The follow-up call must tell the model the chart succeeded, not ask it
    # to re-emit the JSON itself.
    follow_up_messages = adapter.client.chat.completions.create.call_args_list[1].kwargs["messages"]
    tool_message = next(m for m in follow_up_messages if m.get("role") == "tool")
    assert "rendered successfully" in tool_message["content"]


@pytest.mark.asyncio
async def test_invalid_chart_arguments_fall_back_without_crashing():
    adapter = _adapter()
    first = _response(None, [_tool_call("call_1", "render_chart", {"type": "gauge", "title": "x"})])
    second = _response("I can't render a gauge chart; here is the figure instead.")
    adapter.client.chat.completions.create.side_effect = [first, second]

    result = await adapter.complete("Show a gauge chart")

    assert "```chart" not in result
    assert result == "I can't render a gauge chart; here is the figure instead."
    follow_up_messages = adapter.client.chat.completions.create.call_args_list[1].kwargs["messages"]
    tool_message = next(m for m in follow_up_messages if m.get("role") == "tool")
    assert "could not be rendered" in tool_message["content"]


@pytest.mark.asyncio
async def test_multiple_tool_calls_each_validated_independently():
    adapter = _adapter()
    good = {"type": "line", "title": "Trend", "categories": ["2023"], "series": [{"name": "A", "data": [1]}]}
    bad = {"type": "sankey", "title": "Flow"}  # missing nodes/links
    first = _response(None, [
        _tool_call("call_1", "render_chart", good),
        _tool_call("call_2", "render_chart", bad),
    ])
    second = _response("Two charts requested; one could be built.")
    adapter.client.chat.completions.create.side_effect = [first, second]

    result = await adapter.complete("Show two charts")

    assert result.count("```chart") == 1
    assert json.loads(result.split("```chart\n", 1)[1].rsplit("\n```", 1)[0])["type"] == "line"
