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
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult
from app.orchestration.websearch import WebSource

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
    "memory. Use `calculate` for every arithmetic result you state. For a chart, call "
    "`render_chart` with figures from the question or from tool results only. Tool results "
    "are verified evidence alongside the web sources above; if a tool reports no data, say "
    "the figure could not be retrieved. Never mention tools, tool names or tool calls in "
    "the answer."
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


def _rejected_tool_call(exc: Exception) -> tuple[str, str] | None:
    """(tool name, reason) when a provider refused a proposed tool call for
    not matching the declared schema (Groq: HTTP 400, code tool_use_failed),
    else None. Duck-typed on the error body so no provider SDK is imported."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    if not isinstance(error, dict) or error.get("code") != "tool_use_failed":
        return None
    reason = str(error.get("message", "arguments did not match the schema"))[:400]
    try:
        tool = json.loads(error.get("failed_generation") or "{}").get("name", "unknown")
    except (TypeError, ValueError):
        tool = "unknown"
    return str(tool), reason


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
) -> AgentOutcome:
    deadline = time.monotonic() + limits.max_seconds
    tools = registry.function_schemas(granted_permissions)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    outcome = AgentOutcome(text="")
    executed: dict[tuple[str, str], ToolResult] = {}
    executed_count = 0

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
        for index, (call, key) in enumerate(zip(calls, keys)):
            if key in executed or key in to_run:
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
            rejection = _rejected_tool_call(exc)
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
            outcome.text = message.content or ""
            outcome.stop_reason = "final_answer"
            return outcome

        messages.append(_assistant_message(message))
        results = await run_step(step, list(message.tool_calls))
        for call, result in zip(message.tool_calls, results):
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
    else:
        outcome.stop_reason = "max_steps"

    # A limit was hit: one last turn with tools forbidden (declared but
    # tool_choice="none" — Groq rejects a tool call against an implicit none).
    messages.append({
        "role": "user",
        "content": "Stop calling tools. Write the final answer now using only the information gathered above.",
    })
    final = await create("none", deadline - time.monotonic())
    outcome.text = final.choices[0].message.content or ""
    return outcome
