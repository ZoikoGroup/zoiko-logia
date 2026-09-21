"""A slow answer provider must not hold an Ask Kriton request indefinitely."""

import asyncio

import pytest

from app.domains.model_gateway import service
from app.domains.model_gateway.providers.google_adapter import GeminiAdapter


def test_gemini_timeout_uses_groq_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(service, "_PROVIDER_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service, "_select_adapter", lambda: GeminiAdapter.__new__(GeminiAdapter))
    called = []

    async def fake_complete(adapter, prompt, model):
        called.append(type(adapter).__name__)
        if isinstance(adapter, GeminiAdapter):
            await asyncio.sleep(1)
        return "Answer from Groq"

    monkeypatch.setattr(service, "_try_complete", fake_complete)
    assert asyncio.run(service._complete_with_fallback("question")) == "Answer from Groq"
    assert called == ["GeminiAdapter", "GroqAdapter"]


def test_provider_error_is_not_returned_as_answer(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(service, "_select_adapter", lambda: GeminiAdapter.__new__(GeminiAdapter))

    async def fake_complete(adapter, prompt, model):
        return "[Error connecting to Gemini API: unavailable]"

    monkeypatch.setattr(service, "_try_complete", fake_complete)
    with pytest.raises(RuntimeError, match="failed to generate an answer"):
        asyncio.run(service._complete_with_fallback("question"))
