"""
Regression suite for a bug found via live testing: when every attempted
provider fails (e.g. Groq returns a 429 rate-limit error with no further
fallback configured), the raw adapter error string — which can include
internal account/org identifiers and provider-internal rate-limit detail —
was returned as-is and used verbatim as the composed answer text shown to
the user. _complete_with_fallback now sanitizes any surviving "[Error…]"
output into a clean, generic message before returning.

Uses asyncio.run() around each async call rather than an `async def` test
function — this repo's pytest setup has no async-test plugin installed (see
the 8 pre-existing unrelated failures under test_massarius_*/test_tenant_*),
matching the pattern already used in test_histogram_heatmap_and_fixes.py.
"""
import asyncio

from app.domains.model_gateway import service as gateway_service
from app.domains.model_gateway.service import _complete_with_fallback, _PROVIDER_FAILURE_MESSAGE


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

    output = asyncio.run(_complete_with_fallback("some prompt"))

    assert output == _PROVIDER_FAILURE_MESSAGE
    assert "[Error" not in output
    assert "429" not in output
    assert "org_" not in output


def test_successful_provider_output_passes_through_unchanged(monkeypatch):
    monkeypatch.setattr(gateway_service, "_select_adapter", lambda: _AlwaysSucceedsAdapter())

    output = asyncio.run(_complete_with_fallback("some prompt"))

    assert output == "A real, grounded answer."
