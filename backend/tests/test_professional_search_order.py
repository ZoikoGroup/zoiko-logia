"""Tests for discovery-provider ordering.

The order was hardcoded Tavily-then-SerpAPI, with SerpAPI reached only when
Tavily "yields no usable page". With both keys configured — the normal state —
Tavily always answered, so SerpAPI was unreachable in practice while appearing
to be a configured provider. Which provider is primary is now an operator
decision.
"""
import pytest

from app.core.config import get_settings
from app.domains.reference_data import service as reference_service
from app.domains.reference_data.service import (
    _SEARCH_PROVIDERS,
    get_professional_search_bundle,
    professional_search_order,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _DB:
    """record_event_async only needs something session-shaped here; the audit
    write itself is exercised by the reference-data audit tests."""

    async def execute(self, *args, **kwargs):
        return None

    def add(self, *args, **kwargs):
        return None

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def rollback(self):
        return None


def _result(url: str = "https://irs.gov/pub/p946") -> dict:
    return {"title": "Publication 946", "url": url, "content": "Depreciation conventions."}


@pytest.fixture
def _silence_audit(monkeypatch):
    calls: list[str] = []

    async def fake_record(db, **kwargs):
        calls.append(kwargs.get("subject_id", ""))

    monkeypatch.setattr(reference_service, "record_event_async", fake_record)
    return calls


# ── Order resolution ─────────────────────────────────────────────────────


def test_serpapi_is_primary_by_default():
    assert professional_search_order()[0] == "serpapi"


def test_the_order_is_configurable(monkeypatch):
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "tavily,serpapi")
    get_settings.cache_clear()
    assert professional_search_order() == ("tavily", "serpapi")


def test_a_single_provider_can_be_configured(monkeypatch):
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi")
    get_settings.cache_clear()
    assert professional_search_order() == ("serpapi",)


def test_an_unknown_provider_name_is_dropped_not_raised(monkeypatch):
    # A typo in an environment variable must not take down discovery for
    # every query.
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "bing,serpapi")
    get_settings.cache_clear()
    assert professional_search_order() == ("serpapi",)


def test_an_order_resolving_to_nothing_falls_back_to_the_default(monkeypatch):
    # Discovery cannot be switched off by a bad value; clearing a key is how
    # a provider is removed.
    for value in ("", "bing,duckduckgo", ",,,"):
        monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", value)
        get_settings.cache_clear()
        assert professional_search_order() == ("serpapi", "tavily"), value


def test_duplicates_are_collapsed(monkeypatch):
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi,serpapi,tavily")
    get_settings.cache_clear()
    assert professional_search_order() == ("serpapi", "tavily")


def test_whitespace_and_case_are_tolerated(monkeypatch):
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", " TAVILY , SerpAPI ")
    get_settings.cache_clear()
    assert professional_search_order() == ("tavily", "serpapi")


# ── Dispatch ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_primary_provider_answers_and_the_other_is_not_called(monkeypatch, _silence_audit):
    called: list[str] = []

    async def serp(query):
        called.append("serpapi")
        return [_result()]

    async def tavily(query):
        called.append("tavily")
        return [_result()]

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (serp, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setitem(_SEARCH_PROVIDERS, "tavily", (tavily, "tavily.authority_search", "Tavily"))
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi,tavily")
    get_settings.cache_clear()

    bundle, provider = await get_professional_search_bundle(
        _DB(), query="depreciation convention", tenant_id="t1", actor_id="u1")

    assert called == ["serpapi"], "the secondary provider must not be called on success"
    assert provider == "serpapi"
    assert bundle.data == [_result()]


@pytest.mark.asyncio
async def test_an_empty_primary_falls_through_to_the_next(monkeypatch, _silence_audit):
    called: list[str] = []

    async def serp(query):
        called.append("serpapi")
        return []

    async def tavily(query):
        called.append("tavily")
        return [_result()]

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (serp, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setitem(_SEARCH_PROVIDERS, "tavily", (tavily, "tavily.authority_search", "Tavily"))
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi,tavily")
    get_settings.cache_clear()

    _, provider = await get_professional_search_bundle(
        _DB(), query="q", tenant_id="t1", actor_id="u1")
    assert called == ["serpapi", "tavily"]
    assert provider == "tavily"


@pytest.mark.asyncio
async def test_a_raising_primary_does_not_prevent_the_next(monkeypatch, _silence_audit):
    async def serp(query):
        raise RuntimeError("SerpAPI returned status 401")

    async def tavily(query):
        return [_result()]

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (serp, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setitem(_SEARCH_PROVIDERS, "tavily", (tavily, "tavily.authority_search", "Tavily"))
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi,tavily")
    get_settings.cache_clear()

    _, provider = await get_professional_search_bundle(
        _DB(), query="q", tenant_id="t1", actor_id="u1")
    assert provider == "tavily"


@pytest.mark.asyncio
async def test_every_attempt_is_audited_under_its_own_subject_id(monkeypatch, _silence_audit):
    """The ledger has to show which providers were called and what each
    returned, or a silent fallback is indistinguishable from a primary hit."""
    async def empty(query):
        return []

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (empty, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setitem(_SEARCH_PROVIDERS, "tavily", (empty, "tavily.authority_search", "Tavily"))
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi,tavily")
    get_settings.cache_clear()

    await get_professional_search_bundle(_DB(), query="q", tenant_id="t1", actor_id="u1")
    assert _silence_audit == ["serpapi.authority_search", "tavily.authority_search"]


@pytest.mark.asyncio
async def test_all_providers_empty_returns_an_empty_bundle_not_an_error(monkeypatch, _silence_audit):
    async def empty(query):
        return []

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (empty, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setitem(_SEARCH_PROVIDERS, "tavily", (empty, "tavily.authority_search", "Tavily"))
    get_settings.cache_clear()

    bundle, _ = await get_professional_search_bundle(
        _DB(), query="q", tenant_id="t1", actor_id="u1")
    assert bundle.data == []
    assert bundle.source_url == ""


@pytest.mark.asyncio
async def test_the_source_name_is_not_mangled_by_title_casing(monkeypatch, _silence_audit):
    # provider.title() produced "Serpapi"; the display name comes from the
    # registry instead.
    async def serp(query):
        return [_result()]

    monkeypatch.setitem(_SEARCH_PROVIDERS, "serpapi", (serp, "serpapi.authority_search", "SerpAPI"))
    monkeypatch.setenv("PROFESSIONAL_SEARCH_PROVIDER_ORDER", "serpapi")
    get_settings.cache_clear()

    bundle, _ = await get_professional_search_bundle(
        _DB(), query="q", tenant_id="t1", actor_id="u1")
    assert bundle.source_name.startswith("SerpAPI")
    assert "Serpapi" not in bundle.source_name
