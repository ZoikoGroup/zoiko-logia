"""Provider-failure handling for Ask Kriton, found via a live incident on
2026-10-19: the configured Groq key was valid (GET /models returned 200) but
the account had met a spend-alert threshold, so every chat completion returned
HTTP 400 `spend_limit_reached`. The gateway retried the same provider, the raw
provider body (billing URL and all) leaked as the adapter's error string, and
the user saw only the generic "could not compose a response".

Merged on 22 Oct 2026 onto the typed provider errors (errors.py): a block is a
ProviderAccessBlocked exception end to end, not a text sentinel. Groq's
documented hard block is HTTP 400 `blocked_api_access`
(console.groq.com/docs/spend-limits); a rate limit (429) and a model
permission error (403) are different failures with different messages.

These tests pin, all mocking the provider so no live call is made:

  * an account spending block is recognised from the structured provider error,
  * a rate limit, a warning or free text is not reported as a spend block,
  * the adapter raises the typed error, never the raw body, and never retries,
  * a configured fallback provider is used instead,
  * when no fallback is configured the typed spend-limit error is raised,
  * ordinary provider failures and timeouts degrade to the generic failure,
  * the specific, sanitized message reaches the orchestration boundary.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway import service as gateway_service
from app.domains.model_gateway.errors import (
    ProviderAccessBlocked, ProviderAuthenticationFailed, ProviderRateLimited,
    provider_access_failure, provider_request_failure,
)
from app.domains.model_gateway.providers import groq_adapter
from app.orchestration.schemas import MAX_QUERY_CHARS, AskKritonRequest


def _provider_error(status: int, code: str, message: str, kind: str = "invalid_request_error") -> Exception:
    """A stand-in for a groq.APIStatusError carrying the real error body shape."""
    error = Exception(f"Error code: {status}")
    error.status_code = status
    error.body = {"error": {"message": message, "type": kind, "code": code}}
    return error


# The 2026-10-19 incident body, verbatim apart from the account details.
INCIDENT = lambda: _provider_error(  # noqa: E731
    400, "spend_limit_reached",
    "Organization has blocked API access because a spend alert threshold was met. Please visit "
    "https://console.groq.com/settings/billing to manage your spend alerts.",
)


# ── Detection: structured first, conservative fallback ──────────────────────

@pytest.mark.parametrize("error", [
    INCIDENT(),
    _provider_error(400, "blocked_api_access", "API access blocked: spend limit reached."),
    _provider_error(400, "", "Your organization's spending limit has been reached."),
    _provider_error(400, "", "Organization has blocked API access because a spend alert threshold was met."),
], ids=["incident", "documented-code", "wording-limit-reached", "wording-blocked-access"])
def test_an_account_spend_block_is_recognised_from_the_provider_error(error):
    assert isinstance(provider_request_failure(error), ProviderAccessBlocked)


def test_a_rate_limit_is_not_a_spend_block():
    failure = provider_request_failure(_provider_error(429, "rate_limit_exceeded", "Rate limit reached; try again in 3s."))
    assert isinstance(failure, ProviderRateLimited) and not isinstance(failure, ProviderAccessBlocked)


def test_a_spend_alert_that_did_not_block_the_request_is_not_a_spend_block():
    # A notification threshold alongside an ordinary rate limit.
    warning = _provider_error(429, "rate_limit_exceeded", "Rate limit reached. Note: a spend alert threshold was met.")
    assert provider_access_failure(warning) is None
    assert isinstance(provider_request_failure(warning), ProviderRateLimited)


def test_a_model_permission_error_is_an_access_error_not_a_spend_block():
    failure = provider_request_failure(_provider_error(403, "permissions_error", "Model not permitted.", "permissions_error"))
    assert isinstance(failure, ProviderAuthenticationFailed)


def test_free_text_never_counts_as_a_spend_block():
    assert provider_access_failure(Exception("code: spend_limit_reached")) is None
    assert provider_access_failure(Exception("connection reset by peer")) is None


# ── Adapter: typed error, no leaked detail, no retry ────────────────────────

def _adapter(monkeypatch, failure):
    calls = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise failure

    monkeypatch.setenv("GROQ_API_KEY", "test")
    adapter = groq_adapter.GroqAdapter()
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    return adapter, calls


def test_groq_spend_block_raises_the_typed_error_without_the_raw_body(monkeypatch):
    adapter, calls = _adapter(monkeypatch, INCIDENT())
    with pytest.raises(ProviderAccessBlocked) as raised:
        asyncio.run(adapter.complete("hi"))
    assert len(calls) == 1
    assert "console.groq.com" not in str(raised.value) and "spend alert" not in str(raised.value)
    assert "console.groq.com" not in ProviderAccessBlocked.user_message


def test_groq_rate_limit_is_reported_once_without_sleeping_or_retrying(monkeypatch):
    sleeps = []
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=lambda seconds: sleeps.append(seconds)))
    adapter, calls = _adapter(monkeypatch, _provider_error(429, "rate_limit_exceeded", "Rate limit reached."))
    with pytest.raises(ProviderRateLimited):
        asyncio.run(adapter.complete("hi"))
    assert len(calls) == 1 and sleeps == []


# ── Gateway: fallback chain and terminal behaviour ───────────────────────────

class _BlockedAdapter:
    async def complete(self, prompt, model=None):
        raise ProviderAccessBlocked()


class _WorkingAdapter:
    def __init__(self, answer):
        self._answer = answer

    async def complete(self, prompt, model=None):
        return self._answer


def test_all_providers_blocked_raises_the_typed_spend_limit_error(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [])
    with pytest.raises(ProviderAccessBlocked):
        asyncio.run(gateway_service._complete_with_fallback("q"))


def test_missing_fallback_credentials_also_raise_the_typed_spend_limit_error(monkeypatch):
    # Only the blocked provider is configured (no other key), which is exactly
    # the live situation. GROQ_API_KEY is cleared too: load_dotenv() puts
    # backend/.env's real key into os.environ, and _configured_adapters() would
    # otherwise build a real GroqAdapter from it and make a live call.
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderAccessBlocked):
        asyncio.run(gateway_service._complete_with_fallback("q"))


def test_a_blocked_provider_falls_back_to_a_configured_provider(monkeypatch):
    fallback = _WorkingAdapter("Grounded answer from the fallback provider.")
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [fallback])
    assert asyncio.run(gateway_service._complete_with_fallback("q")) == "Grounded answer from the fallback provider."


def test_generic_failure_is_not_reported_as_a_spend_limit(monkeypatch):
    class _GenericFailing:
        async def complete(self, prompt, model=None):
            return "[Error connecting to Groq API: 429 rate limit reached]"

    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _GenericFailing())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [])
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(gateway_service._complete_with_fallback("q"))
    assert not isinstance(excinfo.value, ProviderAccessBlocked)
    assert "429" not in str(excinfo.value) and "[Error" not in str(excinfo.value)


def test_provider_timeout_degrades_to_a_generic_failure(monkeypatch):
    class _SlowAdapter:
        async def complete(self, prompt, model=None):
            await asyncio.sleep(5)
            return "too late"

    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _SlowAdapter())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [])
    monkeypatch.setattr(gateway_service, "_PROVIDER_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(gateway_service._complete_with_fallback("q"))
    assert not isinstance(excinfo.value, ProviderAccessBlocked)


def test_grounded_completion_keeps_the_spend_block_typed(monkeypatch):
    async def _raise(prompt, model=None):
        raise ProviderAccessBlocked()

    monkeypatch.setattr(gateway_service, "_complete_with_fallback", _raise)
    with pytest.raises(ProviderAccessBlocked):
        asyncio.run(gateway_service.run_grounded_completion("q"))


# ── Invalid input is rejected before any model call ──────────────────────────

def test_an_overlong_query_is_rejected_by_the_request_schema():
    with pytest.raises(ValueError):
        AskKritonRequest(query="x" * (MAX_QUERY_CHARS + 1))


# ── The orchestration boundary names the cause, sanitized ────────────────────

@pytest.fixture
def pipeline(monkeypatch):
    from app.orchestration import learned_answers, review, service

    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=None))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: False)
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion",
                        AsyncMock(side_effect=ProviderAccessBlocked()))
    return service


async def test_composition_failure_names_the_spend_limit(pipeline):
    response = await pipeline.ask_kriton(
        AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
        request=AskKritonRequest(query="What is the accrual basis of accounting?"),
    )
    assert response.answer is None
    assert response.next_action is not None
    assert response.next_action.type == "provider_access_blocked"
    assert response.next_action.message == ProviderAccessBlocked.user_message
    assert "spending limit" in response.next_action.message
    assert "spend_limit_reached" not in response.next_action.message


async def test_generic_composition_failure_keeps_the_generic_message(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline.model_gateway_service, "run_grounded_completion",
                        AsyncMock(return_value=pipeline.model_gateway_service._PROVIDER_FAILURE_MESSAGE))
    response = await pipeline.ask_kriton(
        AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
        request=AskKritonRequest(query="What is the accrual basis of accounting?"),
    )
    assert response.next_action is not None and response.next_action.type == "composition_failed"
    assert "spending limit" not in response.next_action.message
