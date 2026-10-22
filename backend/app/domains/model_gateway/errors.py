"""Safe, actionable provider failures; no credentials or raw error bodies."""
from __future__ import annotations

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


def provider_access_failure(exc: BaseException) -> ProviderAccessBlocked | None:
    if isinstance(exc, ProviderAccessBlocked):
        return exc
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if isinstance(error, dict) and error.get("code") == "spend_limit_reached":
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
