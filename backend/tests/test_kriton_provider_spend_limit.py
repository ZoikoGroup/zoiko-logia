"""Provider-failure handling for Ask Kriton, found via a live incident on
2026-10-19: the configured Groq key was valid (GET /models returned 200) but
the account had met a spend-alert threshold, so every chat completion returned
HTTP 400 `spend_limit_reached`. The gateway retried the same provider, the raw
provider body (billing URL and all) leaked as the adapter's error string, and
the user saw only the generic "could not compose a response".

These tests pin the corrected behaviour, all mocking the provider so no live
call is made:

  * an account spending block is recognised from the provider error,
  * the block is reported as a clean sentinel, never the raw body,
  * the blocked provider is not retried for its other model,
  * a configured fallback provider is used instead,
  * when no fallback is configured the specific spend-limit error is raised,
  * ordinary provider failures are NOT reported as a spend limit,
  * a timeout still degrades to the generic failure,
  * the specific, sanitized message reaches the orchestration boundary.

asyncio.run() around each async call, matching this repo's pytest setup (no
async-test plugin; see test_model_gateway_error_sanitization.py).
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway import service as gateway_service
from app.domains.model_gateway.providers import groq_adapter
from app.domains.model_gateway.providers.errors import (
    SPEND_LIMIT_SENTINEL,
    ProviderSpendLimitReached,
    spend_limit_reached,
)
from app.orchestration.schemas import MAX_QUERY_CHARS, AskKritonRequest


class _GroqSpendLimitError(Exception):
    """A stand-in for groq.BadRequestError carrying the real error body shape."""

    status_code = 400
    body = {
        "error": {
            "message": (
                "Organization has blocked API access because a spend alert "
                "threshold was met. Please visit "
                "https://console.groq.com/settings/billing to manage your spend alerts."
            ),
            "type": "invalid_request_error",
            "code": "spend_limit_reached",
        }
    }


# ── Detection ───────────────────────────────────────────────────────────────

def test_spend_limit_is_detected_from_the_error_body():
    assert spend_limit_reached(_GroqSpendLimitError())
    assert spend_limit_reached(Exception("code: spend_limit_reached"))


def test_an_ordinary_provider_error_is_not_a_spend_limit():
    assert not spend_limit_reached(Exception("429 rate limit reached; try again in 3s"))
    assert not spend_limit_reached(Exception("connection reset by peer"))


# ── Adapter: clean sentinel, no leaked detail, no retry ──────────────────────

def test_groq_spend_limit_returns_a_clean_sentinel(monkeypatch):
    class _Completions:
        async def create(self, **kwargs):
            raise _GroqSpendLimitError()

    monkeypatch.setenv("GROQ_API_KEY", "test")
    adapter = groq_adapter.GroqAdapter()
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

    out = asyncio.run(adapter.complete("hi"))

    assert out == SPEND_LIMIT_SENTINEL
    assert "spend alert" not in out
    assert "console.groq.com" not in out
    assert SPEND_LIMIT_SENTINEL.lstrip().startswith("[Error")


# ── Gateway: fallback chain and terminal behaviour ───────────────────────────

class _BlockedAdapter:
    def __init__(self, name="Blocked"):
        self.name = name

    async def complete(self, prompt, model=None):
        return SPEND_LIMIT_SENTINEL


class _WorkingAdapter:
    def __init__(self, answer):
        self._answer = answer

    async def complete(self, prompt, model=None):
        return self._answer


def test_all_providers_blocked_raises_the_spend_limit_error(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [])

    with pytest.raises(ProviderSpendLimitReached):
        asyncio.run(gateway_service._complete_with_fallback("q"))


def test_missing_fallback_credentials_also_raise_the_spend_limit_error(monkeypatch):
    # Only the blocked provider is configured (no other key), which is exactly
    # the live situation: the configured secondary providers had empty keys.
    # GROQ_API_KEY is cleared too: load_dotenv() puts backend/.env's real key
    # into os.environ, and _configured_adapters() would otherwise build a real
    # GroqAdapter from it and make a live call inside this test.
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ProviderSpendLimitReached):
        asyncio.run(gateway_service._complete_with_fallback("q"))


def test_a_blocked_provider_falls_back_to_a_configured_provider(monkeypatch):
    fallback = _WorkingAdapter("Grounded answer from the fallback provider.")
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _BlockedAdapter())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [fallback])

    assert asyncio.run(gateway_service._complete_with_fallback("q")) == \
        "Grounded answer from the fallback provider."


def test_generic_failure_is_not_reported_as_a_spend_limit(monkeypatch):
    class _GenericFailing:
        async def complete(self, prompt, model=None):
            return "[Error connecting to Groq API: 429 rate limit reached]"

    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _GenericFailing())
    monkeypatch.setattr(gateway_service, "_configured_adapters", lambda: [])

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(gateway_service._complete_with_fallback("q"))

    assert not isinstance(excinfo.value, ProviderSpendLimitReached)
    assert "429" not in str(excinfo.value)
    assert "[Error" not in str(excinfo.value)


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
    assert not isinstance(excinfo.value, ProviderSpendLimitReached)


# ── The message that reaches the user ────────────────────────────────────────

def test_grounded_completion_returns_the_specific_sanitized_message(monkeypatch):
    async def _raise(prompt, model=None):
        raise ProviderSpendLimitReached("blocked")

    monkeypatch.setattr(gateway_service, "_complete_with_fallback", _raise)

    out = asyncio.run(gateway_service.run_grounded_completion("q"))

    assert out == gateway_service._PROVIDER_SPEND_LIMIT_MESSAGE
    assert "spending limit" in out and "try again later" in out
    assert "spend_limit_reached" not in out and "console.groq.com" not in out


# ── Invalid input is rejected before any model call ──────────────────────────

def test_an_overlong_query_is_rejected_by_the_request_schema():
    with pytest.raises(ValueError):
        AskKritonRequest(query="x" * (MAX_QUERY_CHARS + 1))


# ── The orchestration boundary returns composition_failed with the cause ─────

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

    async def _spend_limit(prompt, *args, **kwargs):
        return service.model_gateway_service._PROVIDER_SPEND_LIMIT_MESSAGE

    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", _spend_limit)
    return service


async def test_composition_failure_names_the_spend_limit(pipeline):
    response = await pipeline.ask_kriton(
        AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
        request=AskKritonRequest(query="What is the accrual basis of accounting?"),
    )

    assert response.answer is None
    assert response.outcome == "refused"
    assert response.next_action is not None
    assert response.next_action.type == "composition_failed"
    assert response.next_action.message == pipeline._MODEL_PROVIDER_SPEND_LIMIT_MESSAGE
    assert "spending limit" in response.next_action.message
    assert "spend_limit_reached" not in response.next_action.message


async def test_generic_composition_failure_keeps_the_generic_message(pipeline, monkeypatch):
    async def _generic(prompt, *args, **kwargs):
        return pipeline.model_gateway_service._PROVIDER_FAILURE_MESSAGE

    monkeypatch.setattr(pipeline.model_gateway_service, "run_grounded_completion", _generic)

    response = await pipeline.ask_kriton(
        AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
        request=AskKritonRequest(query="What is the accrual basis of accounting?"),
    )

    assert response.next_action.type == "composition_failed"
    assert "spending limit" not in response.next_action.message
