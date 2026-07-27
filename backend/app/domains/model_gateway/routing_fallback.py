"""
Model gateway provider fallback — ZL-T0-08: Application -> Query
Orchestrator -> Model Gateway -> Provider Adapter -> Approved Model
Deployment. Before this module, model_gateway/service.py's
_select_adapter() picked exactly ONE provider (first configured, in
preference order) and had no fallback if that provider's actual API call
failed at request time — a Groq outage would surface as a raw
"[Error connecting to Groq API: ...]" string returned as if it were the
model's own answer, with no retry and no other provider ever attempted.

Every real adapter (GroqAdapter, OpenAIAdapter — confirmed by reading
both) follows the same convention: complete() never raises, it returns a
string starting with "[Error" on failure. This module's failure detection
matches that convention exactly, with a defensive except-Exception
fallback for any adapter that doesn't.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

_ERROR_PREFIX = "[Error"


def _is_failure(output: str) -> bool:
    return output.startswith(_ERROR_PREFIX)


@dataclass
class FallbackResult:
    output: str
    provider_used: str
    attempts: list[str] = field(default_factory=list)
    succeeded: bool = False
    latency_ms: float = 0.0


async def complete_with_fallback(prompt: str, adapters: list[tuple[str, object]]) -> FallbackResult:
    """Tries each (provider_name, adapter) pair in order, moving to the
    next only when the current one fails. Always returns a result, never
    raises — if every adapter fails, returns the LAST failure's
    output/provider so the caller still has something to show, same
    fail-open discipline as every other resilience mechanism in this
    codebase (live_sources.service.fetch_live_data, security_screen, etc.)."""
    start = time.monotonic()
    attempts: list[str] = []
    last_output = ""
    last_provider = ""
    for provider_name, adapter in adapters:
        attempts.append(provider_name)
        try:
            output = await adapter.complete(prompt)
        except Exception as e:
            output = f"[Error: {provider_name} adapter raised {type(e).__name__}: {e}]"
        last_output, last_provider = output, provider_name
        if not _is_failure(output):
            return FallbackResult(
                output=output, provider_used=provider_name, attempts=attempts,
                succeeded=True, latency_ms=(time.monotonic() - start) * 1000,
            )
    return FallbackResult(
        output=last_output, provider_used=last_provider, attempts=attempts,
        succeeded=False, latency_ms=(time.monotonic() - start) * 1000,
    )
