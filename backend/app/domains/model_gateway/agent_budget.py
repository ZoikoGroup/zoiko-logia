"""One generation budget for agent, final-answer and recovery requests.

Preflight uses UTF-8 bytes plus protocol headroom as a conservative estimate
for byte-based tokenizers. Provider usage is authoritative when returned.
This is a per-run allowance, not a provider billing or subscription limit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.domains.model_gateway.errors import ProviderRequestRejected, ProviderRequestTooLarge, provider_request_failure


logger = logging.getLogger(__name__)


class GenerationBudgetExceeded(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def prompt_allowance(messages: list[dict], tools: list[dict] | None = None) -> int:
    payload = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False)
    return len(payload.encode("utf-8")) + 256 + 32 * len(messages)


def request_prompt_estimate(messages: list[dict], tools: list[dict] | None = None) -> int:
    """Estimate provider input separately from the conservative run reservation.

    No tokenizer downloads or API calls. This estimate includes a protocol
    margin but cannot promise an exact count for every model or language.
    """
    payload = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(payload.encode("utf-8")) / 3) + 256 + 32 * len(messages)


@dataclass
class GenerationBudget:
    max_total_tokens: int
    max_completion_tokens: int = 4096
    max_request_tokens: int = 8000
    max_cost_usd: float = 0.0
    price_per_million_tokens: float = 0.0
    tokens_used: int = 0
    estimated_tokens: int = 0
    calls: int = 0
    max_calls: int = 0
    deadline: float | None = None
    closed: bool = False
    terminal_failure: ProviderRequestRejected | None = None
    rate_failures: dict[str, ProviderRequestRejected] = field(default_factory=dict)
    # Sent to GPT-OSS agent calls only when set (AGENT_REASONING_EFFORT).
    # Empty keeps the provider default (medium).
    reasoning_effort: str = ""

    @property
    def cost_usd(self) -> float:
        return self.tokens_used * self.price_per_million_tokens / 1_000_000

    def completion_allowance(self, messages: list[dict], tools: list[dict] | None = None) -> tuple[int, int]:
        remaining = self.max_total_tokens - self.tokens_used
        reason = "token_budget"
        if self.max_cost_usd > 0 and self.price_per_million_tokens > 0:
            cost_remaining = math.floor(self.max_cost_usd * 1_000_000 / self.price_per_million_tokens) - self.tokens_used
            if cost_remaining < remaining:
                remaining, reason = cost_remaining, "cost_budget"
        prompt = prompt_allowance(messages, tools)
        completion = min(self.max_completion_tokens, remaining - prompt)
        if completion <= 0:
            raise GenerationBudgetExceeded(reason)
        if self.max_request_tokens > 0:
            estimate = request_prompt_estimate(messages, tools)
            completion = min(completion, self.max_request_tokens - estimate)
            if completion <= 0:
                raise ProviderRequestTooLarge(origin='local_preflight', input_estimate=estimate,
                                              request_limit=self.max_request_tokens)
        return prompt, completion

    async def create(self, client: Any, *, seconds: float, **kwargs: Any) -> Any:
        sections = kwargs.pop('_context_sections', [])
        if sections and self.max_request_tokens > 0:
            from app.domains.model_gateway.research_context import pack_messages, output_reserve
            packed, before, after = pack_messages(
                kwargs['messages'], kwargs.get('tools'), sections,
                self.max_request_tokens - output_reserve(self.max_request_tokens, self.max_completion_tokens))
            kwargs['messages'] = packed
            logger.info('Research context estimated_input_before=%d estimated_input_after=%d request_limit=%d',
                        before, after, self.max_request_tokens)
        if self.terminal_failure is not None:
            raise self.terminal_failure
        model = str(kwargs.get('model', ''))
        if model in self.rate_failures:
            raise self.rate_failures[model]
        if self.closed:
            raise GenerationBudgetExceeded('request_closed')
        if self.max_calls > 0 and self.calls >= self.max_calls:
            raise GenerationBudgetExceeded('model_call_budget')
        if self.deadline is not None:
            seconds = min(seconds, self.deadline - time.monotonic())
        if seconds <= 0:
            raise asyncio.TimeoutError("Agent deadline exhausted")
        # Forcing "low" here by default (21-22 Oct 2026) coincided with the
        # agent refusing plain accounting questions in its own words in the
        # approved live check, which the medium-reasoning server answered.
        # Low reasoning is therefore opt-in; a caller's own value wins.
        if self.reasoning_effort and "gpt-oss" in str(kwargs.get("model") or ""):
            kwargs.setdefault("reasoning_effort", self.reasoning_effort)
        prompt, completion = self.completion_allowance(kwargs["messages"], kwargs.get("tools"))
        requested = kwargs.pop('max_completion_tokens', kwargs.pop('max_tokens', None))
        if isinstance(requested, int) and requested > 0:
            completion = min(completion, requested)
        # Reserve before sending: exceptions and missing usage must not make
        # a generation free to the next retry. Cancelled calls may be billed.
        reserved = prompt + completion
        self.tokens_used += reserved
        self.estimated_tokens += reserved
        self.calls += 1
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**kwargs, max_completion_tokens=completion), timeout=seconds,
            )
        except Exception as exc:
            # The reservation is kept (a failed call may still be billed); say
            # so, or a run that stops on token_budget cannot be explained
            # (23 Oct 2026: 28,000 and 31,689 reserved tokens never released).
            logger.info("Model call failed (%s); %d reserved tokens kept in the run budget",
                        type(exc).__name__, reserved)
            failure = provider_request_failure(exc)
            if failure is not None:
                if failure.code in {'spend_limit_reached', 'provider_authentication_failed'}:
                    self.terminal_failure = failure
                elif failure.code == 'provider_rate_limited':
                    self.rate_failures[model] = failure
                raise failure from None
            raise
        usage = getattr(response, "usage", None)
        measured = getattr(usage, "total_tokens", None) if usage is not None else None
        if isinstance(measured, int) and measured > 0:
            self.tokens_used += measured - reserved
            self.estimated_tokens -= reserved
        return response
