"""SDK-free classification of provider failures (ZL-ENG-AGT-01 §11).

Provider adapters fail soft — they return a text sentinel instead of raising —
so the gateway needs a marker that separates a non-transient, account-level
block (the provider's billing/spending ceiling is reached, where no retry or
model switch can ever succeed) from an ordinary transient error the same
provider may recover from.

The sentinel is deliberately clean: it never carries the provider's raw error
body, which can include account identifiers and billing URLs.
"""
from __future__ import annotations

SPEND_LIMIT_TOKEN = "provider_spend_limit"

# Returned by an adapter when the provider refused the request because its
# account spending ceiling was reached. Never user-visible text; the gateway
# recognises it and raises ProviderSpendLimitReached instead.
SPEND_LIMIT_SENTINEL = f"[Error: {SPEND_LIMIT_TOKEN}]"


def spend_limit_reached(exc: Exception) -> bool:
    """True when a provider exception reports an account spending-limit block.

    Duck-typed on the error body and message so no provider SDK is imported
    here (see tests/test_model_gateway_single_path.py). Matches Groq's
    `spend_limit_reached` code and the "spend alert" wording of its billing
    block, and the equivalent phrasings other providers use.
    """
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = str(error.get("code", "")).lower()
        message = str(error.get("message", "")).lower()
        if code == "spend_limit_reached" or "spend alert" in message or "spending limit" in message:
            return True
    text = str(exc).lower()
    return (
        "spend_limit_reached" in text
        or "spend alert" in text
        or "spending limit" in text
    )


class ProviderSpendLimitReached(RuntimeError):
    """Every available provider is blocked by its account spending ceiling.

    Distinct from a generic provider failure so callers can show the specific,
    actionable message instead of the generic "try again shortly" one.
    """
