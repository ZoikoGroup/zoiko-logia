"""Safe, actionable provider failures; no credentials or raw error bodies."""
from __future__ import annotations

import re

from groq import APITimeoutError
from httpx import TimeoutException


class ProviderRequestRejected(RuntimeError):
    def __init__(self):
        super().__init__(self.code)


class ProviderAccessBlocked(ProviderRequestRejected):
    code = "spend_limit_reached"
    next_action_type = "provider_access_blocked"
    user_message = (
        "Kriton's AI service is unavailable because the provider account's spending limit was reached. "
        "An administrator needs to restore provider access before you retry."
    )


class ProviderRequestTooLarge(ProviderRequestRejected):
    def __init__(self, *, origin='provider', input_estimate=None, request_limit=None):
        self.origin = origin
        self.input_estimate = input_estimate
        self.request_limit = request_limit
        super().__init__()

    code = "provider_request_too_large"
    next_action_type = "provider_request_too_large"
    user_message = (
        "The AI request could not fit within the service's request-size allowance. "
        "No complete answer was generated. Try a smaller part or ask an administrator to review the request budget."
    )


class ProviderAuthenticationFailed(ProviderRequestRejected):
    code = 'provider_authentication_failed'
    next_action_type = 'provider_access_blocked'
    user_message = "Kriton's AI provider could not authorize this service. An administrator needs to check the provider credentials and model permissions."


class ProviderRateLimited(ProviderRequestRejected):
    code = 'provider_rate_limited'
    next_action_type = 'provider_rate_limited'
    user_message = "Kriton's AI provider has temporarily reached its usage allowance. Please wait for the allowance to reset before retrying."


class RequestBudgetExhausted(ProviderRequestRejected):
    code = 'request_budget_exhausted'
    next_action_type = 'request_budget_exhausted'
    user_message = 'Kriton reached the processing allowance for this request. Any independently verified work is retained; the remaining parts could not be completed.'


class ProviderTimedOut(ProviderRequestRejected, TimeoutError):
    # Preserve the existing deadline/recovery contract while retaining a safe
    # provider-specific audit code.
    code = 'provider_timeout'
    next_action_type = 'composition_failed'
    user_message = (
        'The AI provider timed out before completing the response. '
        'Any independently verified work is retained; retry the unfinished parts shortly.'
    )


class ProviderResponseIncomplete(ProviderRequestRejected):
    code = 'provider_response_incomplete'
    next_action_type = 'composition_failed'
    user_message = (
        "The AI response reached its output limit before it finished. "
        "Any independently verified work is retained; the remaining parts could not be completed."
    )


# Documented hard blocks: Groq answers 400 `blocked_api_access` once the
# organisation's spend limit is reached (console.groq.com/docs/spend-limits).
_HARD_BLOCK_CODES = frozenset({"blocked_api_access", "spend_limit_reached"})
# Known provider wordings for the same block, read from the structured error
# message only.
_HARD_BLOCK_WORDING = re.compile(
    r"\bspend(?:ing)?\s+limit\s+(?:has\s+been\s+|was\s+)?reached\b|\bapi\s+access\s+(?:has\s+been\s+|is\s+)?blocked\b"
    r"|\bblocked\s+(?:the\s+)?api\s+access\b",
    re.I,
)
# An alert can be a notification threshold rather than a block.
_SPEND_ALERT = re.compile(r"\bspend(?:ing)?\s+alert\b", re.I)


def provider_access_failure(exc: BaseException) -> ProviderAccessBlocked | None:
    """A hard account block, from the provider's structured error only.

    Order: documented error code, then known hard-block wording, then a spend
    alert only when the provider refused the request outright (400/402/403 and
    "blocked"). A rate limit or a warning is never a spend block, and free text
    (an exception message, a user's words) never decides."""
    if isinstance(exc, ProviderAccessBlocked):
        return exc
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None
    code = str(error.get("code") or "").lower()
    message = str(error.get("message") or "")
    if code in _HARD_BLOCK_CODES or _HARD_BLOCK_WORDING.search(message):
        return ProviderAccessBlocked()
    status = getattr(exc, "status_code", None)
    if _SPEND_ALERT.search(message) and status in {400, 402, 403} and re.search(r"\bblock", message, re.I):
        return ProviderAccessBlocked()
    return None


def provider_request_failure(exc: BaseException) -> ProviderRequestRejected | None:
    if isinstance(exc, ProviderRequestRejected):
        return exc
    if isinstance(exc, (TimeoutError, APITimeoutError, TimeoutException)):
        return ProviderTimedOut()
    access = provider_access_failure(exc)
    if access is not None:
        return access
    if getattr(exc, 'status_code', None) in {401, 403}:
        return ProviderAuthenticationFailed()
    if getattr(exc, "status_code", None) == 413:
        return ProviderRequestTooLarge()
    if getattr(exc, 'status_code', None) == 429:
        return ProviderRateLimited()
    return None
