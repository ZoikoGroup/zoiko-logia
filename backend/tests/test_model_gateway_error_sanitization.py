"""
Regression suite for a bug found via live testing: when every attempted
provider fails (e.g. Groq returns a 429 rate-limit error with no further
fallback configured), the raw adapter error string — which can include
internal account/org identifiers and provider-internal rate-limit detail —
was returned as-is and used verbatim as the composed answer text shown to
the user. _complete_with_fallback now raises instead whenever every
provider fails, so a corrupt "[Error…]" string can never be mistaken for an
answer at the gateway boundary; callers that surface text to users
(run_grounded_completion, run_test_prompt) translate that into the clean,
generic _PROVIDER_FAILURE_MESSAGE themselves.

Uses asyncio.run() around each async call rather than an `async def` test
function — this repo's pytest setup has no async-test plugin installed (see
the 8 pre-existing unrelated failures under test_massarius_*/test_tenant_*),
matching the pattern already used in test_histogram_heatmap_and_fixes.py.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway import service as gateway_service
from app.domains.model_gateway.service import _complete_with_fallback


class _AlwaysFailsAdapter:
    async def complete(self, prompt: str, model: str | None = None) -> str:
        return (
            "[Error connecting to Groq API: Error code: 429 - "
            "{'error': {'message': 'Rate limit reached...', 'code': 'rate_limit_exceeded'}}]"
        )


class _AlwaysSucceedsAdapter:
    async def complete(self, prompt: str, model: str | None = None) -> str:
        return "A real, grounded answer."


def test_raw_provider_error_never_reaches_the_composed_answer(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _AlwaysFailsAdapter())
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(_complete_with_fallback("some prompt"))

    raw = str(excinfo.value)
    assert "failed to generate an answer" in raw
    assert "[Error" not in raw
    assert "429" not in raw
    assert "org_" not in raw


def test_successful_provider_output_passes_through_unchanged(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _AlwaysSucceedsAdapter())

    output = asyncio.run(_complete_with_fallback("some prompt"))

    assert output == "A real, grounded answer."


def test_gemini_error_falls_back_to_groq(monkeypatch):
    class FailingGemini(gateway_service.GeminiAdapter):
        async def complete(self, prompt: str, model: str | None = None) -> str:
            return "[Error connecting to Gemini API: transient 503]"

    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: FailingGemini())
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    monkeypatch.setattr(
        gateway_service,
        "_try_complete",
        AsyncMock(side_effect=["[Error connecting to Gemini API: transient 503]", "Groq fallback answer."]),
    )
    assert asyncio.run(_complete_with_fallback("prompt")) == "Groq fallback answer."
