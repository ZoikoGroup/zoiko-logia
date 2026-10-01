"""The governed agent loop (model_gateway/agent.py) against a scripted client."""
import json
from types import SimpleNamespace

from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentLimits, clean_agent_text, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec, build_default_registry
from app.orchestration.websearch import WebSource


def _call(name: str, args: dict, call_id: str = "c1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _reply(content: str = "", tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class ScriptedClient:
    """chat.completions.create returns the scripted replies in order and
    records every request (a copy of the messages and the tool_choice)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


class _LookupArgs(BaseModel):
    key: str


def _registry(counter: list[str]) -> ToolRegistry:
    async def lookup(args: _LookupArgs) -> ToolResult:
        counter.append(args.key)
        source = WebSource(title=f"Source {args.key}", url=f"https://example.com/{args.key}", snippet=args.key)
        return ToolResult(ok=True, content=f"value for {args.key}", sources=(source,))

    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="lookup", version="1.0", description="Look up.", args_model=_LookupArgs, handler=lookup,
        data_source="test", risk_level="low", timeout_seconds=1.0,
    ))
    return registry


async def _run(client, registry, limits=AgentLimits(), question="question", **hooks):
    return await run_agent(
        client, model="m", system_prompt="sys", user_prompt=question,
        registry=registry, granted_permissions=frozenset(), limits=limits, **hooks,
    )


async def test_answer_without_tools_is_one_step() -> None:
    client = ScriptedClient([_reply("Direct answer.")])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Direct answer." and outcome.steps == 1
    assert outcome.stop_reason == "final_answer" and outcome.tool_calls == []
    assert client.requests[0]["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in client.requests[0]["tools"]} == {"lookup"}


async def test_tool_result_is_fed_back_and_evidence_collected() -> None:
    executed: list[str] = []
    started: list[str] = []
    done = []

    async def on_start(name):
        started.append(name)

    async def on_done(record):
        done.append(record)

    client = ScriptedClient([_reply(tool_calls=[_call("lookup", {"key": "gdp"})]), _reply("GDP is up.")])
    outcome = await _run(client, _registry(executed), on_tool_start=on_start, on_tool_done=on_done)

    assert outcome.text == "GDP is up." and outcome.steps == 2
    assert executed == ["gdp"] and started == ["lookup"]
    assert [s.url for s in outcome.sources] == ["https://example.com/gdp"]
    assert len(done) == 1 and done[0].ok and done[0].source_count == 1 and len(done[0].arguments_hash) == 32
    tool_message = client.requests[1]["messages"][-1]
    assert tool_message == {"role": "tool", "tool_call_id": "c1", "content": "value for gdp"}


async def test_identical_call_is_never_executed_twice() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1")]),
        # Same arguments with different key order/spacing is still the same call.
        _reply(tool_calls=[SimpleNamespace(id="c2", function=SimpleNamespace(name="lookup", arguments='{ "key" : "a" }'))]),
        _reply("done"),
    ])
    outcome = await _run(client, _registry(executed))
    assert executed == ["a"]
    assert [r.error_code for r in outcome.tool_calls] == [None, "duplicate_call"]
    assert "Already called" in client.requests[2]["messages"][-1]["content"]
    assert len(outcome.sources) == 1


async def test_parallel_calls_in_one_step_run_and_duplicates_within_step_collapse() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[
            _call("lookup", {"key": "uk"}, "c1"), _call("lookup", {"key": "us"}, "c2"),
            _call("lookup", {"key": "uk"}, "c3"),
        ]),
        _reply("compared"),
    ])
    outcome = await _run(client, _registry(executed))
    assert sorted(executed) == ["uk", "us"]
    assert [r.error_code for r in outcome.tool_calls] == [None, None, "duplicate_call"]
    # Every proposed call gets its own tool message, in order.
    assert [m["tool_call_id"] for m in client.requests[1]["messages"][-3:]] == ["c1", "c2", "c3"]


async def test_tool_call_budget_is_enforced() -> None:
    executed: list[str] = []
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1"), _call("lookup", {"key": "b"}, "c2")]),
        _reply("partial answer"),
    ])
    outcome = await _run(client, _registry(executed), limits=AgentLimits(max_tool_calls=1))
    assert executed == ["a"]
    assert [r.error_code for r in outcome.tool_calls] == [None, "budget_exhausted"]


async def test_step_limit_forces_a_final_answer_with_tools_forbidden() -> None:
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"}, "c1")]),
        _reply(tool_calls=[_call("lookup", {"key": "b"}, "c2")]),
        _reply("best effort answer"),
    ])
    outcome = await _run(client, _registry([]), limits=AgentLimits(max_steps=2))
    assert outcome.stop_reason == "max_steps" and outcome.text == "best effort answer"
    assert client.requests[-1]["tool_choice"] == "none"
    assert "Stop calling tools" in client.requests[-1]["messages"][-1]["content"]


async def test_exhausted_time_budget_skips_straight_to_final_answer() -> None:
    client = ScriptedClient([_reply("answer from what was given")])
    outcome = await _run(client, _registry([]), limits=AgentLimits(max_seconds=1.0))
    assert outcome.stop_reason == "time_budget"
    assert client.requests[0]["tool_choice"] == "none"


async def test_unknown_tool_is_reported_back_not_raised() -> None:
    client = ScriptedClient([_reply(tool_calls=[_call("delete_ledger", {})]), _reply("cannot do that")])
    outcome = await _run(client, _registry([]))
    assert outcome.tool_calls[0].error_code == "unknown_tool"
    assert "Unknown tool" in client.requests[1]["messages"][-1]["content"]


async def test_chart_and_calculation_through_the_real_registry() -> None:
    chart = {"type": "bar", "title": "Revenue", "categories": ["Q1", "Q2"], "series": [{"name": "Rev", "data": [100, 150]}]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("calculate", {"expression": "(150 - 100) / 100 * 100", "label": "Growth %"}, "c1"),
                           _call("render_chart", chart, "c2")]),
        _reply("Revenue grew 50%."),
    ])
    outcome = await _run(client, build_default_registry(), question="Revenue went from 100 to 150.")
    assert "= 50 " in client.requests[1]["messages"][-2]["content"]
    assert len(outcome.artifacts) == 1 and outcome.artifacts[0].startswith("```chart\n")
    assert json.loads(outcome.artifacts[0].split("\n")[1])["series"][0]["data"] == [100, 150]


async def test_chart_placeholder_image_is_stripped_when_a_chart_is_attached() -> None:
    chart = {"type": "line", "title": "Debt", "categories": ["2023", "2024"], "series": [{"name": "D", "data": [114.7, 115.8]}]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", chart)]),
        _reply("**Debt**\n\nThe chart below shows it.\n\n![Chart]\n\n![Debt (2015-2024)](attachment://chart.png)\n\n"
               "*Debt rose.* See ![logo](https://x.y/l.png)"),
    ])
    outcome = await _run(client, build_default_registry(), question="Debt was 114.7 then 115.8.")
    assert outcome.text == "**Debt**\n\nThe chart below shows it.\n\n*Debt rose.* See ![logo](https://x.y/l.png)"


async def test_placeholder_kept_when_no_chart_was_rendered() -> None:
    client = ScriptedClient([_reply("Text ![Chart]")])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Text ![Chart]"


def test_chart_pseudo_tag_is_stripped_when_a_chart_is_attached() -> None:
    text = "Brazil: 211 912 000\nThe bar chart below visualises these figures.\n\n<chart-rendered>\n"
    assert clean_agent_text(text, chart_attached=True) == (
        "Brazil: 211 912 000\nThe bar chart below visualises these figures."
    )


def test_tool_arguments_written_as_text_are_stripped() -> None:
    text = (
        "Debt = 28 trillion × 115.8 / 100\n\nUsing the calculation tool:\n\n"
        '{"expression":"28*115.8/100","label":"Debt in dollars"}\n\nResult: $32.424 trillion.'
    )
    assert clean_agent_text(text, chart_attached=False) == (
        "Debt = 28 trillion × 115.8 / 100\n\nResult: $32.424 trillion."
    )


def test_json_inside_a_code_fence_is_kept() -> None:
    text = 'Example payload:\n```json\n{"amount": 100}\n```'
    assert clean_agent_text(text, chart_attached=False) == text


async def test_invalid_chart_is_rejected_without_an_artifact() -> None:
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", {"type": "gauge", "title": "x"})]),
        _reply("Could not chart it."),
    ])
    outcome = await _run(client, build_default_registry())
    assert outcome.artifacts == [] and outcome.tool_calls[0].error_code == "invalid_arguments"


class _ToolUseFailed(Exception):
    """Shape of Groq's 400 when it rejects a proposed call against the schema."""

    def __init__(self):
        super().__init__("tool_use_failed")
        self.body = {"error": {
            "code": "tool_use_failed",
            "message": "parameters for tool lookup did not match schema: /key: expected string",
            "failed_generation": '{"name": "lookup", "arguments": {"key": [1, 2]}}',
        }}


async def test_provider_rejected_tool_call_is_corrected_not_fatal() -> None:
    executed: list[str] = []
    replies = [_ToolUseFailed(), _reply(tool_calls=[_call("lookup", {"key": "fixed"})]), _reply("ok")]

    class RejectingClient(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    client = RejectingClient(replies)
    outcome = await _run(client, _registry(executed))
    assert outcome.text == "ok" and executed == ["fixed"]
    assert outcome.tool_calls[0].tool == "lookup" and outcome.tool_calls[0].error_code == "invalid_arguments"
    assert "rejected as invalid" in client.requests[1]["messages"][-1]["content"]


async def test_other_provider_errors_still_raise_for_fallback() -> None:
    class Boom(ScriptedClient):
        async def _create(self, **kwargs):
            raise RuntimeError("503 from provider")

    try:
        await _run(Boom([]), _registry([]))
    except RuntimeError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("provider outage must propagate so orchestration falls back")


async def test_same_data_charted_twice_keeps_only_the_last_chart() -> None:
    data = {"categories": ["2024", "2025"], "series": [{"name": "Inflation", "data": [12.63, 3.55]}]}
    other = {"categories": ["2024", "2025"], "series": [{"name": "GDP", "data": [2.5, 3.1]}]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", {"type": "line", "title": "Inflation", **data}, "c1")]),
        _reply(tool_calls=[_call("render_chart", {"type": "bar", "title": "Inflation (bar)", **data}, "c2"),
                           _call("render_chart", {"type": "bar", "title": "GDP", **other}, "c3")]),
        _reply("Charts below."),
    ])
    outcome = await _run(client, build_default_registry(), question="Inflation 12.63, 3.55; GDP 2.5, 3.1.")
    specs = [json.loads(a.split("\n")[1]) for a in outcome.artifacts]
    assert [(s["type"], s["title"]) for s in specs] == [("bar", "Inflation (bar)"), ("bar", "GDP")]


async def test_chart_written_in_text_is_dropped_when_a_tool_chart_exists() -> None:
    chart = {"type": "bar", "title": "GDP", "categories": ["2025"], "series": [{"name": "Japan", "data": [1.19]}]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", chart)]),
        _reply("GDP below.\n\n```chart\n" + json.dumps(chart) + "\n```\n"),
    ])
    outcome = await _run(client, build_default_registry(), question="Japan grew 1.19%.")
    assert len(outcome.artifacts) == 1 and "```chart" not in outcome.text and outcome.text == "GDP below."


async def test_valid_chart_written_in_text_becomes_the_validated_chart() -> None:
    chart = {"type": "line", "title": "GDP", "categories": ["2025"], "series": [{"name": "Japan", "data": [1.19]}]}
    client = ScriptedClient([_reply("GDP below.\n\n```chart\n" + json.dumps(chart) + "\n```")])
    outcome = await _run(client, _registry([]))
    assert len(outcome.artifacts) == 1 and outcome.artifacts[0].startswith("```chart\n") and "```" not in outcome.text


async def test_unparseable_generation_is_retried_not_fatal() -> None:
    class Unparseable(Exception):
        body = {"error": {"code": "output_parse_failed", "message": "Parsing failed."}}

    replies = [Unparseable(), _reply("Recovered answer.")]

    class FlakyClient(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    client = FlakyClient(replies)
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Recovered answer." and outcome.steps == 2
    assert "could not be parsed" in client.requests[1]["messages"][-1]["content"]


async def test_empty_reply_is_recovered_not_a_fallback() -> None:
    # The model answered with nothing (all reasoning, no content): this used
    # to raise "empty answer" and throw away every fetched figure.
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "a"})]),
        _reply(""),
        _reply("Answer from the data."),
    ])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Answer from the data." and outcome.stop_reason == "final_answer"
    assert client.requests[2]["tool_choice"] == "none"


async def test_forced_final_turn_error_answers_from_evidence_without_tools() -> None:
    class ToolCallAgainstNone(Exception):
        body = {"error": {"code": "tool_use_failed", "message": "Tool choice is none, but model called a tool"}}

    class Client(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    client = Client([
        _reply(tool_calls=[_call("lookup", {"key": "a"})]),
        ToolCallAgainstNone(),
        _reply("Final from evidence."),
    ])
    outcome = await _run(client, _registry([]), AgentLimits(max_steps=1))
    assert outcome.text == "Final from evidence." and outcome.stop_reason == "max_steps"
    last = client.requests[-1]
    assert "tools" not in last and "value for a" in last["messages"][-1]["content"]


async def test_chart_of_figures_never_fetched_is_refused() -> None:
    invented = {"type": "candlestick", "title": "AAPL", "categories": ["d1", "d2"],
                "ohlc": [[311.2, 312.9, 309.4, 314.1], [312.9, 315.5, 311.0, 316.8]]}
    client = ScriptedClient([
        _reply(tool_calls=[_call("render_chart", invented)]),
        _reply("No chart."),
    ])
    outcome = await _run(client, build_default_registry())
    assert outcome.artifacts == [] and outcome.tool_calls[0].error_code == "unverified_figures"
    assert "Fetch the data" in client.requests[1]["messages"][-1]["content"]


def test_chart_figures_match_question_tool_results_rounding_and_units() -> None:
    from app.domains.model_gateway.agent import unverified_chart_values

    evidence = "Sales ₹4.2L in Jan, ₹3.8L in Feb. Revenue: $716,924,000,000. Debt 2020: 124.509"
    chart = {"type": "bar", "title": "x", "categories": ["a", "b", "c", "d"],
             "series": [{"name": "s", "data": [420000, 3.8, 716.92, 124.51]}]}
    assert unverified_chart_values(json.dumps(chart), evidence) == []
    chart["series"][0]["data"].append(999.99)
    assert unverified_chart_values(json.dumps(chart), evidence) == [999.99]


async def test_requested_chart_that_was_never_drawn_gets_one_reminder() -> None:
    chart = {"type": "line", "title": "NVDA", "categories": ["d1", "d2"], "series": [{"name": "c", "data": [217.55, 227.98]}]}
    client = ScriptedClient([
        _reply("The candlestick chart below shows it."),        # claims a chart it never drew
        _reply(tool_calls=[_call("render_chart", chart)]),
        _reply("Chart below."),
    ])
    outcome = await run_agent(
        client, model="m", system_prompt="sys", user_prompt="NVDA closed 227.98 then 217.55. Chart it.",
        registry=build_default_registry(), granted_permissions=frozenset(), chart_requested=True,
    )
    assert len(outcome.artifacts) == 1 and outcome.text == "Chart below."
    assert "render_chart was never called" in client.requests[1]["messages"][-1]["content"]


async def test_no_reminder_when_no_chart_was_asked_for() -> None:
    client = ScriptedClient([_reply("Plain answer.")])
    outcome = await _run(client, _registry([]))
    assert outcome.text == "Plain answer." and len(client.requests) == 1


def test_chart_request_detection_is_explicit() -> None:
    from app.domains.model_gateway.agent import chart_requested

    assert chart_requested("Show the last 30 days as a candlestick")
    assert chart_requested("Chart both for 10 years")
    assert not chart_requested("Compare GDP growth of India and China")


async def test_conditional_chart_does_not_override_agents_no_chart_decision() -> None:
    from app.domains.model_gateway.agent import chart_requested

    question = "Is Japan unemployment higher than Germany? If yes, chart both for 10 years."
    client = ScriptedClient([_reply("No. Japan is lower, so no chart is needed.")])
    outcome = await run_agent(
        client, model="m", system_prompt="sys", user_prompt=question,
        registry=build_default_registry(), granted_permissions=frozenset(),
        chart_requested=chart_requested(question),
    )
    assert outcome.artifacts == []
    assert len(client.requests) == 1
    assert outcome.text.startswith("No.")


async def test_evidence_rule_applies_to_final_and_recovery_generations() -> None:
    client = ScriptedClient([
        _reply(tool_calls=[_call("lookup", {"key": "debt"})]),
        _reply(""),
        _reply("Debt ratio rose. Retrieved data does not establish the causes."),
    ])
    outcome = await _run(client, _registry([]), AgentLimits(max_steps=1))
    assert "does not establish" in outcome.text
    for request in client.requests:
        assert "Numerical time series do not establish WHY" in request["messages"][0]["content"]


def test_numeric_evidence_does_not_support_causal_prose():
    from app.domains.model_gateway.agent import ground_economic_narrative

    source = WebSource(title="Debt", url="https://example.com", snippet="2023: 114.73; 2024: 115.77")
    result = ToolResult(ok=True, content=source.snippet, sources=(source,))
    text = (
        "| Year | Debt |\n| 2024 | 115.77 |\n"
        "The ratio rose in 2024.\n"
        "The ratio fell as economic activity recovered and the fiscal position improved.\n"
        "The rise was driven by infrastructure spending.\n"
        "The change reflects stimulus and higher interest costs."
    )
    cleaned = ground_economic_narrative(text, [result])
    assert "115.77" in cleaned and "ratio rose" in cleaned
    assert "infrastructure" not in cleaned and "stimulus" not in cleaned
    assert "recovered" not in cleaned
    assert "do not state the causes" in cleaned


def test_directly_supported_cause_is_preserved():
    from app.domains.model_gateway.agent import ground_economic_narrative

    passage = "The rise was driven by infrastructure spending."
    source = WebSource(title="Analysis", url="https://example.com", snippet=passage)
    assert ground_economic_narrative(passage, [ToolResult(ok=True, content=passage, sources=(source,))]) == passage


async def test_agent_final_answer_filters_unsupported_economic_causes():
    async def economic(_args):
        return ToolResult(ok=True, content="2024: 115.77", sources=(
            WebSource(title="Debt", url="https://example.com", snippet="2024: 115.77"),
        ))
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="get_economic_indicator", version="1", description="Data", args_model=_LookupArgs,
        handler=economic, data_source="test", risk_level="low", timeout_seconds=1,
    ))
    client = ScriptedClient([
        _reply(tool_calls=[_call("get_economic_indicator", {"key": "debt"})]),
        _reply("Debt was 115.77.\nThe rise was driven by fiscal stimulus."),
    ])
    outcome = await _run(client, registry)
    assert "115.77" in outcome.text and "stimulus" not in outcome.text
    assert "do not state the causes" in outcome.text


async def test_evidence_answer_drops_tool_instructions_and_retries_a_tool_attempt() -> None:
    # Live failure: the no-tools recovery call still carried "call render_chart…",
    # the model called it anyway, and Groq rejected that turn as well.
    from app.domains.model_gateway.agent import AGENT_TOOL_INSTRUCTIONS

    class CalledATool(Exception):
        body = {"error": {"code": "tool_use_failed", "message": "Tool choice is none, but model called a tool",
                          "failed_generation": '{"name": "render_chart"}'}}

    class Client(ScriptedClient):
        async def _create(self, **kwargs):
            self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    client = Client([
        _reply(tool_calls=[_call("lookup", {"key": "a"})]),
        CalledATool(),          # forced final turn (tool_choice=none)
        CalledATool(),          # first no-tools recovery call
        _reply("Plain final answer."),
    ])
    outcome = await run_agent(
        client, model="m", system_prompt="sys", user_prompt="question" + AGENT_TOOL_INSTRUCTIONS,
        registry=_registry([]), granted_permissions=frozenset(), limits=AgentLimits(max_steps=1),
    )
    assert outcome.text == "Plain final answer."
    for request in client.requests[2:]:
        prompt = request["messages"][-1]["content"]
        assert "tools" not in request and AGENT_TOOL_INSTRUCTIONS not in prompt and "NO TOOLS ARE AVAILABLE" in prompt


def test_reasoning_and_comparisons_are_not_mistaken_for_causal_claims():
    """The first version dropped whole lines containing "because", deleting
    the answer's actual conclusion and adding an unrelated causes note."""
    from app.domains.model_gateway.agent import ground_economic_narrative

    source = WebSource(title="Unemployment", url="https://example.com", snippet="Japan 2025: 2.45; Germany 2025: 3.71")
    result = ToolResult(ok=True, content=source.snippet, sources=(source,))
    text = (
        "Japan's unemployment (2.45%) is lower than Germany's (3.71%).\n"
        "Because Japan's rate is lower, no chart is needed.\n"
        "The chart reflects the figures above."
    )
    assert ground_economic_narrative(text, [result]) == text


def test_only_the_causal_sentence_is_removed_from_a_line():
    from app.domains.model_gateway.agent import ground_economic_narrative

    source = WebSource(title="Debt", url="https://example.com", snippet="2020: 124.51; 2022: 112.72")
    result = ToolResult(ok=True, content=source.snippet, sources=(source,))
    text = "Debt peaked at 124.51% in 2020. It rose due to pandemic stimulus. It then fell to 112.72% by 2022."
    cleaned = ground_economic_narrative(text, [result])
    assert "peaked at 124.51% in 2020" in cleaned and "fell to 112.72% by 2022" in cleaned
    assert "pandemic" not in cleaned


def test_clarifying_reply_is_recognised_only_without_data() -> None:
    from app.domains.model_gateway.agent import AgentOutcome, ToolCallRecord, is_agent_clarification

    ask = "Could you please provide your salary amount and the currency you want it converted to?"
    assert is_agent_clarification(ask, AgentOutcome(text=ask))
    fetched = AgentOutcome(text=ask, tool_calls=[ToolCallRecord(1, "get_exchange_rate", "h", True, None, 5, 1)])
    assert not is_agent_clarification(ask, fetched)
    answer = "Japan's GDP per capita is ₹34,50,762.09 (2025)."
    assert not is_agent_clarification(answer, AgentOutcome(text=answer))
    rhetorical = "Is 200 ÷ 500 = 0.4%? No — it is 40%."
    assert not is_agent_clarification(rhetorical, AgentOutcome(text=rhetorical))


def test_tool_names_never_reach_the_answer_but_ordinary_words_stay() -> None:
    assert clean_agent_text("Gap = 1.26 pp (calculated with `calculate`).", chart_attached=False) == "Gap = 1.26 pp."
    assert clean_agent_text("Rate from `get_exchange_rate` is 95.98.", chart_attached=False) == (
        "Rate from the ECB reference rates is 95.98."
    )
    assert clean_agent_text("We calculate the margin as 25%.", chart_attached=False) == "We calculate the margin as 25%."


def test_clarification_without_a_question_mark_is_recognised() -> None:
    from app.domains.model_gateway.agent import AgentOutcome, is_agent_clarification

    text = ("To convert your salary to euros I need two pieces of information: the amount and its currency. "
            "Once you provide those details, I can retrieve the rate.")
    assert is_agent_clarification(text, AgentOutcome(text=text))


def test_causal_clause_is_trimmed_but_the_trend_is_kept() -> None:
    from app.domains.model_gateway.agent import ground_economic_narrative

    source = WebSource(title="Debt", url="https://example.com", snippet="2020: 124.51; 2022: 112.72")
    result = ToolResult(ok=True, content=source.snippet, sources=(source,))
    text = ("- **2021-2022:** Debt fell to 112.72% in 2022 as the economy recovered and stimulus ended.\n"
            "The data indicate that after the pandemic-related surge, debt has been easing.")
    cleaned = ground_economic_narrative(text, [result])
    assert "- **2021-2022:** Debt fell to 112.72% in 2022." in cleaned
    assert "Debt has been easing." in cleaned
    assert "stimulus" not in cleaned and "pandemic" not in cleaned and "recovered" not in cleaned


def test_no_duplicate_note_when_the_answer_already_disclaims_causes() -> None:
    from app.domains.model_gateway.agent import ground_economic_narrative

    source = WebSource(title="Debt", url="https://example.com", snippet="2024: 115.77")
    result = ToolResult(ok=True, content=source.snippet, sources=(source,))
    cleaned = ground_economic_narrative(
        "The rise reflects fiscal stimulus. The specific drivers are not detailed in the source data.", [result])
    assert cleaned == "The specific drivers are not detailed in the source data."
