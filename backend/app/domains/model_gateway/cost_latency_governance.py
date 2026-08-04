"""
Model gateway cost/latency governance — rough per-provider cost estimation,
logged alongside model_gateway/service.py's existing model_run_completed
audit event rather than a new parallel tracking system.

Cost figures are approximate published list-price per 1K tokens — not
billing-accurate, meant for relative cost visibility/alerting, not
invoicing. Token counts are estimated from character length (~4 chars per
token, the standard rough heuristic for English text), not a real
tokenizer — good enough for relative visibility, not exact.
"""
from __future__ import annotations

# Approximate USD cost per 1,000 tokens, input/output. Rough and
# occasionally stale by design — update when a provider's pricing changes;
# this is a visibility/alerting signal, not what actually gets billed.
_COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "groq": {"input": 0.00005, "output": 0.00008},   # llama-3.1-8b-instant, approx
    "openai": {"input": 0.00015, "output": 0.0006},  # gpt-4o-mini, approx
    "mock": {"input": 0.0, "output": 0.0},
}
_DEFAULT_COST = {"input": 0.0001, "output": 0.0003}

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_cost_usd(provider: str, input_text: str, output_text: str) -> float:
    rates = _COST_PER_1K_TOKENS.get(provider, _DEFAULT_COST)
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)
    return round(
        (input_tokens / 1000) * rates["input"] + (output_tokens / 1000) * rates["output"],
        6,
    )


# In-process running total — not a persisted, tenant-scoped budget (that
# would need a dedicated table, a bigger undertaking than this foundational
# pass). Resets on process restart; a basic safety-net signal within one
# process's lifetime, not a multi-tenant billing control.
_session_cost_usd = 0.0


def record_cost(cost_usd: float) -> float:
    global _session_cost_usd
    _session_cost_usd += cost_usd
    return _session_cost_usd


def get_session_cost_usd() -> float:
    return _session_cost_usd
