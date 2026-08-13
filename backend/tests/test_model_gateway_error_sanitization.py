"""
Regression suite for a bug found via live testing: when every attempted
provider fails (e.g. Groq returns a 429 rate-limit error with no further
fallback configured), the raw adapter error string — which can include
internal account/org identifiers and provider-internal rate-limit detail —
was returned as-is and used verbatim as the composed answer text shown to
the user. _complete_with_fallback now sanitizes any surviving "[Error…]"
output into a clean, generic message.

Follow-up from further live testing: sanitizing was necessary but not
sufficient. A clean message returned as the completion still reached the user
as a composed answer — the turn was reported outcome="answered", carrying live
citations, a disclaimer and follow-up suggestions wrapped around a sentence
that answered nothing. The failure is now RAISED as ProviderUnavailable, so
orchestration's existing composition_failed handler returns a refusal with no
answer body. These tests assert both halves: the raise, and that no provider
internals survive in what the exception carries into audit/user-facing copy.

Uses asyncio.run() around each async call rather than an `async def` test
function — this repo's pytest setup has no async-test plugin installed (see
the 8 pre-existing unrelated failures under test_massarius_*/test_tenant_*),
matching the pattern already used in test_histogram_heatmap_and_fixes.py.
"""
import asyncio

import pytest

from app.domains.model_gateway import service as gateway_service
from app.domains.model_gateway.service import (
    _complete_with_fallback,
    _PROVIDER_FAILURE_MESSAGE,
    ProviderUnavailable,
)


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
    monkeypatch.setattr(gateway_service, "os", gateway_service.os)  # no GROQ_API_KEY fallback path needed here
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailable) as excinfo:
        asyncio.run(_complete_with_fallback("some prompt"))

    # str() is what reaches audit records and user-facing copy — it must be the
    # generic message, never the provider's own text.
    message = str(excinfo.value)
    assert message == _PROVIDER_FAILURE_MESSAGE
    assert "[Error" not in message
    assert "429" not in message
    assert "org_" not in message
    # The raw text is still available for server-side diagnosis.
    assert "429" in excinfo.value.detail


def test_provider_failure_is_raised_not_returned_as_an_answer(monkeypatch):
    """The regression that mattered: a returned message is indistinguishable
    from a composed answer, so orchestration reported a provider outage as
    outcome="answered" with citations and follow-up prompts around it."""
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _AlwaysFailsAdapter())
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailable):
        asyncio.run(gateway_service.run_grounded_completion("some prompt"))


def test_successful_provider_output_passes_through_unchanged(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _AlwaysSucceedsAdapter())

    output = asyncio.run(_complete_with_fallback("some prompt"))

    assert output == "A real, grounded answer."
