"""One generation budget for agent, final-answer and recovery requests.

Preflight uses UTF-8 bytes plus protocol headroom as a conservative estimate
for byte-based tokenizers. Provider usage is authoritative when returned.
This is a per-run allowance, not a provider billing or subscription limit.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.domains.model_gateway.errors import ProviderRequestRejected, ProviderRequestTooLarge, provider_request_failure


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
