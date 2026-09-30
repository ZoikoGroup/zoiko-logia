"""The governed single-agent loop behind Ask Kriton's agent mode.

    model ──► proposes tool calls ──► ToolRegistry.execute() ──► results
      ▲                                                            │
      └──────────────────── fed back as tool messages ◄────────────┘
    …until the model answers without calling a tool, or a limit is hit.

The model decides WHAT to fetch; everything else is enforced here or in the
registry, never left to the model:

  - hard limits on steps, total tool calls and wall-clock time
  - an identical call (same tool, same arguments) is never executed twice —
    the model is handed the earlier result instead, which stops loops
  - every tool call is reported to the caller (for the audit trail and the
    progress indicator), including rejected, failed and duplicate ones
  - when a limit is hit the model is asked for a final answer with tools
    forbidden, using whatever it has gathered so far

Provider-agnostic: works with any OpenAI-compatible chat.completions client
(Groq's AsyncGroq today). Raises only on provider/transport failure, which
the caller treats as "fall back to the non-agent path".
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult
from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
from app.orchestration.websearch import WebSource
from app.orchestration.chart_intent import allows_automatic_chart

StopReason = Literal["final_answer", "max_steps", "time_budget"]

# Minimum time kept back for the forced final answer after a limit is hit.
_FINAL_ANSWER_RESERVE_SECONDS = 15.0

# Appended to the grounded answering prompt in agent mode. That prompt says to
# answer from its numbered web sources only; tool results must count too.
AGENT_TOOL_INSTRUCTIONS = (
    "\n\n=== Tools ===\n"
    "You can call tools to fetch live exchange rates, official economic statistics and "
    "market/company data, to calculate exactly, and to render charts. Call a tool whenever "
    "the answer depends on a current or official figure — never state such figures from "
    "memory. The web sources above are NOT the only evidence: if they lack a figure the "
    "tools can fetch (a country's statistics, an exchange rate, a company's financials or "
    "share prices), call the tool — never answer that 'the sources do not contain' it. "
    "Fetch data before charting it. A short follow-up ('add Thailand', 'now for Japan', "
    "'compare it with Malaysia') repeats the previous question with that change — fetch "
    "what it needs rather than asking what was meant. Follow conditions in the question "
    "('if yes, chart…', 'otherwise…'): do only the branch that applies. "
    "Use `calculate` for every arithmetic result you state, including ratios, "
    "differences and 'x times' comparisons. For a chart, call `render_chart` with figures "
    "from the question, the conversation or tool results only — never write a ```chart block "
    "yourself. When the user asks for a chart without saying of what, or asks to change a "
    "chart ('make it a bar chart'), chart the figures from the most recent earlier answer in "
    "the conversation that has figures; ask only if the conversation has none. For a trend or "
    "'last N years', use the most recent years a tool returned, always ending with the latest "
    "year available — never drop it. Round money to 2 decimal places (or to the whole unit "
    "for large amounts) and show one final figure, not an unrounded one beside it. In any "
    "working you show, write each input exactly as it went into `calculate` — the product "
    "of the numbers shown must equal the result shown; never show rounded inputs beside a "
    "result computed from unrounded ones (10,713.29 × 95.99 is not 1,028,315.04). Whenever "
    "you use an exchange rate, state its date as the tool gave it. When you compare or "
    "convert a statistic, state the year of each figure. Do not add a currency symbol the "
    "question did not use. When you "
    "explain WHY a figure moved, only state causes that the sources or tool results give; "
    "otherwise describe the numerical trend and say its causes were not established. "
    "Do not add 'commonly cited' explanations to a specific period. Tool results "
    "are verified evidence alongside the web sources above; if a tool reports no data, say "
    "the figure could not be retrieved. A question about economic or company figures is in "
    "scope even when part of it names something with no data (a planet, a fictional or "
    "unknown country or company): fetch the real part and say the rest has no data — do "
    "not reply with the out-of-scope message. Never mention tools, tool names or tool calls in "
    "the answer, and never write a tool's arguments as text — call the tool instead. Do not "
    "write any placeholder for the chart; it is attached automatically."
)


# Where models expect the chart to appear they write a placeholder — a
# markdown image with no real web URL ("![Chart]",
# "![Debt](attachment://chart.png)") or a pseudo-tag ("<chart-rendered>").
# It renders as a broken image or stray text; the real chart is attached
# below the answer from render_chart's artifact.
_CHART_PLACEHOLDER = re.compile(
    r"[ \t]*(?:!\[[^\]\n]*\](?:\((?!https?://)[^)\n]*\)|(?!\())|</?chart[\w-]*\s*/?>)[ \t]*\n?",
    re.IGNORECASE,
)
# Tool plumbing a model sometimes writes into prose instead of calling the
# tool: a bare JSON-arguments line, or a lead-in like "Using the calculation
# tool:". Only whole lines outside code fences are removed.
_ARGUMENTS_LINE = re.compile(r'^\s*\{\s*"[^"\n]+"\s*:.*\}\s*$')
_TOOL_LEAD_IN = re.compile(r"^\s*(?:using|via|with)\b[^\n]{0,60}\btool\b[^\n]{0,40}:?\s*$", re.IGNORECASE)


_TOOL_NAMES = r"(?:calculate|render_chart|get_exchange_rate|get_economic_indicator|get_market_data)"
_TOOL_PARENTHETICAL = re.compile(
    rf"\s*\((?:[^()\n]{{0,40}}\b)?`?{_TOOL_NAMES}`?(?:\b[^()\n]{{0,20}})?\)", re.I,
)
_TOOL_NAME_IN_PROSE = re.compile(rf"`?\b({_TOOL_NAMES})\b`?")
_TOOL_PLAIN_NAME = {
    "calculate": "exact calculation", "render_chart": "the chart",
    "get_exchange_rate": "the ECB reference rates", "get_economic_indicator": "World Bank data",
    "get_market_data": "market data",
}


def _strip_tool_plumbing(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (_ARGUMENTS_LINE.match(line) or _TOOL_LEAD_IN.match(line)):
            continue
        elif not in_fence:
            line = _TOOL_PARENTHETICAL.sub("", line)
            # Only snake_case names — plain "calculate" is an ordinary word.
            line = _TOOL_NAME_IN_PROSE.sub(
                lambda m: _TOOL_PLAIN_NAME[m.group(1)] if "_" in m.group(1) or m.group(0).startswith("`")
                else m.group(0), line)
        lines.append(line)
    return "\n".join(lines)


def clean_agent_text(text: str, *, chart_attached: bool) -> str:
    text = _strip_tool_plumbing(text)
    if chart_attached:
        text = _CHART_PLACEHOLDER.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# An explicit chart request in the user's own question (not the broader
# wants_visual(), which also fires on "compare" or "trend").
_CHART_REQUEST = re.compile(r"\b(chart|charts|graph|graphs|plot|candlestick|visuali[sz]e)\b", re.I)


def chart_requested(question: str) -> bool:
    return bool(_CHART_REQUEST.search(question or "")) and allows_automatic_chart(question or "")


# A sentence explaining WHY an economic figure moved: a causal connector AND
# a real-world cause. Both are required — a connector alone is ordinary
# reasoning ("Because Japan's rate is lower, no chart is needed"), and
# removing whole lines on "because" alone deleted exactly that conclusion.
_CAUSAL_CONNECTOR = re.compile(
    r"\b(?:because|due to|driven by|attribut(?:ed|able) to|caused by|owing to|as a result of|"
    r"on the back of|fu?ell?ed by|led to|resulted in|contributed to|reflect(?:s|ed|ing)?|"
    r"linked to|thanks to|amid|as (?:the )?econom\w+|as economic activity)\b",
    re.I,
)
_EXTERNAL_CAUSE = re.compile(
    r"\b(?:stimulus|pandemic|covid|lockdown|recession|crisis|war|conflict|sanction|tariff|"
    r"monetary|fiscal|policy|policies|central bank|interest rates?|rate (?:hikes?|cuts?)|"
    r"spending|tax (?:cuts?|receipts|revenues?|reforms?)|borrowing|deficits?|demand|supply|"
    r"commodit\w*|oil|energy|food prices|currency|depreciation of|devaluation|exchange rate|"
    r"investment|consumption|exports? (?:boom|surge|slump)|reforms?|elections?|government|"
    r"recover\w*|fiscal position|economic activity)\b",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*])")


# Causes that are attributions on their own, even with no connector
# ("after the pandemic-related surge").
_STRONG_CAUSE = re.compile(r"\b(?:pandemic|covid(?:-19)?|stimulus|lockdowns?)\b", re.I)
_CAUSES_ALREADY_DISCLAIMED = re.compile(
    r"\b(?:causes?|drivers?|reasons?)\b[^.\n]{0,60}\bnot (?:established|detailed|stated|given|explained|provided)"
    r"|\bdo(?:es)? not (?:state|establish|explain|detail) (?:the |their |its )?(?:causes?|drivers?|reasons?)",
    re.I,
)
_TREND_WORDS = re.compile(r"\d|\b(?:rose|fell|rise|fall|increase\w*|decrease\w*|declin\w*|peak\w*|"
                          r"grew|growth|drop\w*|climb\w*|eas\w*|rebound\w*|stable|stabilis\w*|stabiliz\w*|higher|lower)\b", re.I)


def _without_cause(sentence: str) -> str | None:
    """The sentence with its unsupported causal part removed, or None when
    nothing worth keeping is left. "Debt fell to 112.72% in 2022 as the
    economy recovered." keeps "Debt fell to 112.72% in 2022." — deleting the
    whole sentence dropped the trend itself."""
    ending = "." if sentence.rstrip().endswith(".") else ""
    connector = _CAUSAL_CONNECTOR.search(sentence)
    if connector and _EXTERNAL_CAUSE.search(sentence[connector.start():]):
        head = sentence[:connector.start()].rstrip(" ,;:—–-")
        return head + ending if _TREND_WORDS.search(head) and len(head.split()) >= 3 else None
    # No connector: drop the comma/dash-separated clause carrying the cause.
    clauses = re.split(r"(,\s+|\s+[—–-]\s+)", sentence)
    kept = [c for c in clauses[::2] if not _STRONG_CAUSE.search(c) and not _EXTERNAL_CAUSE.search(c)]
    head = ", ".join(c.strip(" .") for c in kept if c.strip(" ."))
    head = head[:1].upper() + head[1:]
    return head + ending if head and _TREND_WORDS.search(head) and len(head.split()) >= 3 else None


def ground_economic_narrative(text: str, results: list[ToolResult]) -> str:
    """Keep numeric-only economic evidence from acquiring causal prose.

    Trims the part of a sentence that explains a movement by an outside cause
    the sources do not state ("… due to pandemic stimulus", "after the
    pandemic-related surge"), keeping the description of the numbers; drops
    "commonly cited" boilerplate. Comparisons, conclusions ("Because Japan's
    rate is lower, no chart is needed"), tables, chart payloads and quoted
    source text are kept. A note is added only when something was removed
    and the answer does not already say the causes are not established.
    """
    evidence = " ".join(
        " ".join(source.snippet.casefold().split()) for result in results for source in result.sources
    )
    kept: list[str] = []
    in_fence = False
    removed = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence or line.lstrip().startswith(("|", "```")):
            kept.append(line)
            continue
        prefix = re.match(r"^\s*(?:[-*]\s+|\d+\.\s+)?", line).group(0)
        sentences = _SENTENCE.split(line[len(prefix):])
        survivors = []
        for sentence in sentences:
            normalized = " ".join(sentence.strip(" *->").casefold().split())
            causal = (
                (_CAUSAL_CONNECTOR.search(sentence) and _EXTERNAL_CAUSE.search(sentence))
                or _STRONG_CAUSE.search(sentence)
            )
            if re.search(r"\bcommonly cited\b", sentence, re.I) and normalized not in evidence:
                removed = True
                continue
            if causal and normalized and normalized not in evidence:
                removed = True
                trimmed = _without_cause(sentence)
                if trimmed:
                    survivors.append(trimmed)
                continue
            survivors.append(sentence)
        if survivors:
            kept.append(prefix + " ".join(survivors))
        elif not line.strip():
            kept.append("")
    if removed and not _CAUSES_ALREADY_DISCLAIMED.search("\n".join(kept)):
        kept.append("\n*The figures come from official statistics, which do not state the causes of these changes.*")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


# A reply that asks the user for missing input rather than answering.
_ASKS_FOR_INPUT = re.compile(
    r"\b(?:could|can|would) you (?:please )?(?:provide|share|specify|tell me|let me know|confirm|clarify)|"
    r"\bplease (?:provide|share|specify|tell me|let me know|confirm|clarify)|"
    r"\blet me know (?:the|which|what|your|how)|\bwhich (?:currency|country|countries|amount|company|"
    r"year|period|indicator|metric)\b[^.?]*\?|\bwhat (?:is|was) (?:your|the) (?:amount|salary|figure)\b|"
    r"\b(?:once|when|if) you (?:provide|share|give|tell|specify|let me know)|"
    r"\bI (?:will |would )?need (?:the|a few|two|three|some|more|your)\b[^.]*\b(?:information|details|amount|figures?)",
    re.I,
)


def is_agent_clarification(text: str, outcome: "AgentOutcome") -> bool:
    """True when the agent's reply is a request for missing information —
    no data fetched, no chart, short, and asking the user for input."""
    fetched = any(call.ok and call.tool != "calculate" for call in outcome.tool_calls)
    return (
        not fetched and not outcome.artifacts and len(text) < 900
        and bool(_ASKS_FOR_INPUT.search(text))
    )


def with_agent_instructions(grounded_prompt: str) -> str:
    """The exact agent-mode user prompt — shared by orchestration and the
    evaluation runner so the eval measures what production sends."""
    return grounded_prompt + AGENT_TOOL_INSTRUCTIONS


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = 5
    max_tool_calls: int = 8
    max_seconds: float = 75.0


@dataclass(frozen=True)
class ToolCallRecord:
    step: int
    tool: str
    # Hash, not raw arguments: arguments can echo user text, and the audit
    # trail stores digests of model I/O per the privacy-by-design doctrine.
    arguments_hash: str
    ok: bool
    error_code: str | None
    duration_ms: int
    source_count: int


@dataclass
class AgentOutcome:
    text: str
    sources: list[WebSource] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    stop_reason: StopReason = "final_answer"


ToolStartHook = Callable[[str], Awaitable[None]]
ToolDoneHook = Callable[[ToolCallRecord], Awaitable[None]]


def _canonical_arguments(raw: str | None) -> str:
    try:
        return json.dumps(json.loads(raw or "{}"), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return raw or ""


def _provider_error(exc: Exception) -> dict | None:
    # Duck-typed on the error body so no provider SDK is imported.
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    return error if isinstance(error, dict) else None


def unparseable_generation(exc: Exception) -> bool:
    """True when the provider could not parse the model's own output (Groq:
    HTTP 400, code output_parse_failed) — a malformed generation, not a bad
    request, so asking again can succeed."""
    error = _provider_error(exc)
    return error is not None and error.get("code") == "output_parse_failed"


def rejected_tool_call(exc: Exception) -> tuple[str, str] | None:
    """(tool name, reason) when a provider refused a proposed tool call for
    not matching the declared schema (Groq: HTTP 400, code tool_use_failed),
    else None."""
    error = _provider_error(exc)
    if error is None or error.get("code") != "tool_use_failed":
        return None
    reason = str(error.get("message", "arguments did not match the schema"))[:400]
    try:
        tool = json.loads(error.get("failed_generation") or "{}").get("name", "unknown")
    except (TypeError, ValueError):
        tool = "unknown"
    return str(tool), reason


_CHART_FENCE = re.compile(r"[ \t]*```chart[ \t]*\n(.*?)\n[ \t]*```[ \t]*\n?", re.DOTALL)


_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# A figure may be charted in another unit than it was stated in: "₹4.2L" as
# 420000, $716,924,000,000 as 716.92 (billions).
_SCALES = (1.0, 1e2, 1e3, 1e5, 1e6, 1e7, 1e9, 1e12)


def _chart_values(spec: dict) -> list[float]:
    """The data values of a render_chart call — not axis maxima or indices."""
    values: list[float] = []
    for series in spec.get("series") or []:
        if isinstance(series, dict):
            values += [v for v in series.get("data") or [] if isinstance(v, (int, float))]
            values += [v for point in series.get("points") or [] for v in point if isinstance(v, (int, float))]
    for key in ("data", "links"):
        values += [item["value"] for item in spec.get(key) or [] if isinstance(item, dict)
                   and isinstance(item.get("value"), (int, float))]
    values += [v for row in spec.get("ohlc") or [] for v in row if isinstance(v, (int, float))]
    return values


def unverified_chart_values(raw_arguments: str | None, evidence: str) -> list[float]:
    """Chart values that appear nowhere in the evidence (the question, the
    conversation, web sources and tool results so far), allowing rounding and
    a change of unit. One run drew a 15-day candlestick chart BEFORE fetching
    any prices; this is what stops a chart of invented numbers."""
    try:
        spec = json.loads(raw_arguments or "{}")
    except ValueError:
        return []
    if not isinstance(spec, dict):
        return []
    known = [float(token.replace(",", "")) for token in _NUMBER.findall(evidence)]
    known = [value * scale for value in known for scale in _SCALES] + [value / scale for value in known for scale in _SCALES]

    def found(value: float) -> bool:
        if value == 0:
            return True
        tolerance = max(abs(value) * 0.002, 0.006)
        return any(abs(value - k) <= tolerance for k in known)

    return [value for value in _chart_values(spec) if not found(float(value))]


def _final_text(content: str | None, outcome: AgentOutcome) -> str:
    """The answer text, with every chart in outcome.artifacts.

    Models copy the ```chart blocks they see in earlier answers and write one
    into the text as well as calling render_chart, which showed two charts.
    A chart in the text is kept only when no tool chart exists, and only
    after the same validation render_chart applies; identical charts collapse.
    """
    text = content or ""
    for match in _CHART_FENCE.finditer(text):
        if outcome.artifacts:
            break
        try:
            outcome.artifacts.append(build_chart_fence(match.group(1)))
        except ChartToolError:
            continue
    text = _CHART_FENCE.sub("", text)
    outcome.artifacts[:] = _one_chart_per_dataset(outcome.artifacts)
    return clean_agent_text(text, chart_attached=bool(outcome.artifacts))


def _one_chart_per_dataset(artifacts: list[str]) -> list[str]:
    """Keep the LAST chart drawn of each dataset. A model asked for "a chart"
    drew the same figures as a line and then again as a bar; the later call
    is its final choice. Charts of different data are all kept."""
    def dataset(fence: str) -> str:
        try:
            spec = json.loads(fence.split("\n", 1)[1].rsplit("\n", 1)[0])
        except (IndexError, ValueError):
            return fence
        return json.dumps({k: v for k, v in spec.items() if k not in ("type", "title", "stacked")}, sort_keys=True)

    last = {dataset(fence): index for index, fence in enumerate(artifacts)}
    return [fence for index, fence in enumerate(artifacts) if last[dataset(fence)] == index]


def _assistant_message(message: Any) -> dict:
    # Hand-built rather than message.model_dump(): providers reject some
    # response-only fields when echoed back (see GroqAdapter).
    return {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "type": "function",
             "function": {"name": call.function.name, "arguments": call.function.arguments}}
            for call in message.tool_calls
        ],
    }


async def run_agent(
    client: Any,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    granted_permissions: frozenset[str],
    limits: AgentLimits = AgentLimits(),
    on_tool_start: ToolStartHook | None = None,
    on_tool_done: ToolDoneHook | None = None,
    chart_requested: bool = False,
) -> AgentOutcome:
    deadline = time.monotonic() + limits.max_seconds
    # Apply to every generation, including forced-final and recovery calls.
    # Numeric observations support descriptions of change, not causal claims.
    system_prompt += (
        "\nEvidence rule: Numerical time series do not establish WHY values changed. "
        "Explain a trend by describing the observed rises, falls and turning points. "
        "State a specific cause only when an available source passage explicitly supports "
        "that cause for that period; identify the supporting source. Only if the user asked "
        "why, and no source gives the cause, say the retrieved data does not establish it — "
        "otherwise do not mention causes at all. Do not fill this gap with plausible "
        "stories about stimulus, spending, tax receipts, interest costs or GDP growth. "
        "A debt-to-GDP ratio alone does not establish how either debt or GDP changed."
    )
    reminded_chart = False
    tools = registry.function_schemas(granted_permissions)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    outcome = AgentOutcome(text="")
    executed: dict[tuple[str, str], ToolResult] = {}
    executed_count = 0

    def final_text(text: str) -> str:
        if any(name == "get_economic_indicator" and result.ok
               for (name, _), result in executed.items()):
            text = ground_economic_narrative(text, list(executed.values()))
        return _final_text(text, outcome)

    async def create(tool_choice: str, budget: float):
        return await asyncio.wait_for(
            client.chat.completions.create(
                model=model, messages=messages, tools=tools, tool_choice=tool_choice, temperature=0.0,
            ),
            timeout=max(budget, 1.0),
        )

    async def execute(name: str, raw: str | None) -> tuple[ToolResult, int]:
        started = time.monotonic()
        if on_tool_start:
            await on_tool_start(name)
        result = await registry.execute(name, raw, granted_permissions=granted_permissions)
        return result, int((time.monotonic() - started) * 1000)

    async def run_step(step: int, calls: list[Any]) -> list[ToolResult]:
        """Plan every call in the order proposed (duplicate and budget checks
        are order-dependent), run the genuinely new ones concurrently — a
        comparison fans out — then record each call's outcome in order."""
        nonlocal executed_count
        keys = [(call.function.name, _canonical_arguments(call.function.arguments)) for call in calls]
        to_run: dict[tuple[str, str], Any] = {}
        budget_hit: set[int] = set()
        unverified: dict[int, list[float]] = {}
        evidence = user_prompt + "\n" + "\n".join(result.content for result in executed.values())
        for index, (call, key) in enumerate(zip(calls, keys)):
            if key in executed or key in to_run:
                continue
            if key[0] == "render_chart":
                missing = unverified_chart_values(call.function.arguments, evidence)
                if missing:
                    unverified[index] = missing
                    continue
            if executed_count >= limits.max_tool_calls:
                budget_hit.add(index)
                continue
            executed_count += 1
            to_run[key] = call

        ran = await asyncio.gather(*(execute(call.function.name, call.function.arguments) for call in to_run.values()))
        fresh = dict(zip(to_run, ran))

        results: list[ToolResult] = []
        recorded: set[tuple[str, str]] = set()
        for index, key in enumerate(keys):
            duration_ms = 0
            if index in budget_hit:
                result = ToolResult.failure(
                    "budget_exhausted", "Tool-call limit reached. Answer now with the information already gathered.",
                )
            elif index in unverified:
                shown = ", ".join(f"{value:g}" for value in unverified[index][:6])
                result = ToolResult.failure(
                    "unverified_figures",
                    f"Chart not drawn: these values are not in the question, the conversation or any "
                    f"tool result: {shown}. Fetch the data (or calculate the values) first, then chart "
                    "only those figures.",
                )
            elif key in fresh and key not in recorded:
                result, duration_ms = fresh[key]
                recorded.add(key)
                executed[key] = result
                outcome.sources.extend(result.sources)
                outcome.artifacts.extend(result.artifacts)
            else:
                earlier = executed[key]
                result = ToolResult(
                    ok=earlier.ok, error_code="duplicate_call",
                    content=f"Already called with the same arguments; that result was:\n{earlier.content}",
                )
            record = ToolCallRecord(
                step=step, tool=key[0],
                arguments_hash=hashlib.sha256(key[1].encode()).hexdigest()[:32],
                ok=result.ok, error_code=result.error_code, duration_ms=duration_ms,
                source_count=0 if result.error_code == "duplicate_call" else len(result.sources),
            )
            outcome.tool_calls.append(record)
            if on_tool_done:
                await on_tool_done(record)
            results.append(result)
        return results

    for step in range(1, limits.max_steps + 1):
        remaining = deadline - time.monotonic() - _FINAL_ANSWER_RESERVE_SECONDS
        if remaining <= 0:
            outcome.stop_reason = "time_budget"
            break
        outcome.steps = step
        try:
            response = await create("auto", remaining)
        except Exception as exc:
            if unparseable_generation(exc):
                # Consumes a step, so a model that keeps failing still ends.
                messages.append({
                    "role": "user",
                    "content": "Your last reply could not be parsed. Reply again: either call a "
                               "tool with valid JSON arguments, or write the final answer as text.",
                })
                continue
            rejection = rejected_tool_call(exc)
            if rejection is None:
                raise
            # The provider validated the proposed call against the tool's
            # schema itself and refused it (Groq: 400 tool_use_failed), so no
            # tool message exists to answer. Tell the model what was wrong and
            # let it retry — this consumes a step, so it cannot loop forever.
            outcome.tool_calls.append(ToolCallRecord(
                step=step, tool=rejection[0], arguments_hash="", ok=False,
                error_code="invalid_arguments", duration_ms=0, source_count=0,
            ))
            if on_tool_done:
                await on_tool_done(outcome.tool_calls[-1])
            messages.append({
                "role": "user",
                "content": f"Your last tool call was rejected as invalid: {rejection[1]} "
                           "Correct the arguments to match the tool's schema and try again.",
            })
            continue
        message = response.choices[0].message
        if not message.tool_calls:
            outcome.stop_reason = "final_answer"
            if (
                chart_requested and not outcome.artifacts and not reminded_chart
                and step < limits.max_steps and (message.content or "").strip()
            ):
                # Asked for a chart, answered "the chart below…" without ever
                # calling render_chart. One reminder, then accept the answer.
                reminded_chart = True
                messages.append({"role": "assistant", "content": message.content})
                messages.append({"role": "user", "content": (
                    "The question asks for a chart, but render_chart was never called, so no chart "
                    "exists. Call render_chart now with the fetched figures, then give the final "
                    "answer. If there is genuinely no data to chart, answer again saying so."
                )})
                continue
            if (message.content or "").strip():
                outcome.text = final_text(message.content)
                return outcome
            # An empty reply (the model spent it all on reasoning) — ask for
            # the answer below instead of failing the whole agent run.
            break

        messages.append(_assistant_message(message))
        results = await run_step(step, list(message.tool_calls))
        for call, result in zip(message.tool_calls, results):
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
    else:
        outcome.stop_reason = "max_steps"

    # A limit was hit (or the reply was empty): one last turn with tools
    # forbidden (declared but tool_choice="none" — Groq rejects a tool call
    # against an implicit none).
    messages.append({
        "role": "user",
        "content": "Stop calling tools. Write the final answer now using only the information gathered above.",
    })
    text = ""
    try:
        final = await create("none", deadline - time.monotonic())
        text = final.choices[0].message.content or ""
    except Exception:
        # The model still tried to call a tool (Groq: 400) — fall through to
        # a call with no tools declared at all.
        pass
    if not text.strip():
        text = await _answer_from_evidence(client, model, system_prompt, user_prompt, executed, deadline)
    outcome.text = final_text(text)
    return outcome


async def _answer_from_evidence(
    client: Any, model: str, system_prompt: str, user_prompt: str,
    executed: dict[tuple[str, str], ToolResult], deadline: float,
) -> str:
    """Last resort for a final answer: a fresh conversation with no tools
    declared, the gathered tool results pasted in as text. Two agent runs in
    one test session fell back to the non-agent path — losing every fetched
    figure — because the forced final turn errored or came back empty.

    The tool instructions are stripped from the prompt: left in, the model
    still emitted a render_chart call with no tools declared, and Groq
    rejected that too ("Tool choice is none, but model called a tool")."""
    evidence = "\n\n".join(
        f"[{name}] {result.content}" for (name, _), result in executed.items() if result.ok
    ) or "(no data could be retrieved)"
    question = user_prompt.replace(AGENT_TOOL_INSTRUCTIONS, "")
    instruction = (
        "NO TOOLS ARE AVAILABLE in this turn — do not call any function or tool. Write the "
        "final answer as plain text now, using only the data below. Any chart that was "
        "drawn is attached automatically; never write chart JSON."
    )
    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model, temperature=0.0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": (
                            f"{question}\n\n=== Data already retrieved (verified) ===\n{evidence}\n\n{instruction}"
                        )},
                    ],
                ),
                timeout=max(deadline - time.monotonic(), 15.0),
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            if attempt or rejected_tool_call(exc) is None:
                raise
            instruction = "Answer in plain prose only. " + instruction
    return ""
