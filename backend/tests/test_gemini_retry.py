"""Bounded retry behavior for transient Gemini failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.model_gateway.providers.google_adapter import GeminiAdapter


class ProviderFailure(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code


def _adapter_with_calls(*effects):
    adapter = GeminiAdapter.__new__(GeminiAdapter)
    generate = AsyncMock(side_effect=list(effects))
    adapter.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    adapter.api_key = "dummy"
    return adapter, generate


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_transient_status_retries_once_then_succeeds(status):
    adapter, generate = _adapter_with_calls(ProviderFailure(status), SimpleNamespace(text="answer"))
    with patch("app.domains.model_gateway.providers.google_adapter.asyncio.sleep", new_callable=AsyncMock) as sleep:
        assert await adapter.complete("prompt") == "answer"
    assert generate.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_retryable_client_failure_does_not_retry():
    adapter, generate = _adapter_with_calls(ProviderFailure(400))
    with patch("app.domains.model_gateway.providers.google_adapter.asyncio.sleep", new_callable=AsyncMock) as sleep:
        output = await adapter.complete("prompt")
    assert output.startswith("[Error connecting to Gemini API:")
    assert generate.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_transient_failure_returns_error_for_groq_fallback():
    adapter, generate = _adapter_with_calls(ProviderFailure(503), ProviderFailure(503))
    with patch("app.domains.model_gateway.providers.google_adapter.asyncio.sleep", new_callable=AsyncMock):
        output = await adapter.complete("prompt")
    assert output.startswith("[Error connecting to Gemini API:")
    assert generate.await_count == 2
