"""GroqAdapter.complete recovers from a provider-rejected render_chart call
(which failed whole answers, e.g. a radar chart) and never returns the same
chart twice."""
import json
from types import SimpleNamespace

from app.domains.model_gateway.providers.groq_adapter import GroqAdapter


class _ToolUseFailed(Exception):
    def __init__(self):
        super().__init__("tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed", "message": "/indicators: expected array",
                               "failed_generation": '{"name": "render_chart", "arguments": {}}'}}


def _reply(content="", tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _chart_call(args, call_id="c1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name="render_chart", arguments=json.dumps(args)))


class _Client:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _adapter(client):
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = client
    return adapter


BAR = {"type": "bar", "title": "Sales", "categories": ["Apr", "May"], "series": [{"name": "Sales", "data": [2.1, 2.6]}]}


async def test_rejected_chart_call_is_corrected_and_retried() -> None:
    client = _Client([_ToolUseFailed(), _reply(tool_calls=[_chart_call(BAR)]), _reply("Sales rose.")])
    text = await _adapter(client).complete("chart please")
    assert "```chart" in text and not text.startswith("[Error")
    assert "rejected as invalid" in client.requests[1]["messages"][-1]["content"]


async def test_two_rejections_fall_back_to_a_plain_answer() -> None:
    client = _Client([_ToolUseFailed(), _ToolUseFailed(), _reply("Here is the data as a table.")])
    text = await _adapter(client).complete("chart please")
    assert text == "Here is the data as a table."
    assert client.requests[-1]["tool_choice"] == "none"


async def test_other_provider_errors_still_surface_as_errors() -> None:
    class Down(Exception):
        pass

    text = await _adapter(_Client([Down("503")])).complete("hello")
    assert text.startswith("[Error")


async def test_model_typed_chart_is_dropped_when_the_tool_chart_exists() -> None:
    prose_with_chart = 'Trend below.\n```chart\n{"type": "bar"}\n```'
    client = _Client([_reply(tool_calls=[_chart_call(BAR, "c1"), _chart_call(BAR, "c2")]), _reply(prose_with_chart)])
    text = await _adapter(client).complete("chart please")
    assert text.count("```chart") == 1  # neither the typed copy nor the duplicate call survive
