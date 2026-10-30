import pytest


@pytest.fixture(autouse=True)
def _block_live_model_transport(monkeypatch):
    """Ordinary tests cannot spend model tokens using a developer's key."""
    import os
    if os.getenv("RUN_LIVE_LLM_TESTS") == "1":
        return
    for name in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    import groq

    def blocked(*args, **kwargs):
        pytest.fail("Live model transport is disabled in offline tests; mock the model response")

    async def blocked_async(*args, **kwargs):
        blocked()

    monkeypatch.setattr(groq.Groq, "request", blocked)
    monkeypatch.setattr(groq.AsyncGroq, "request", blocked_async)


@pytest.fixture(autouse=True)
def _isolate_external_services(monkeypatch):
    # app/core/config.py loads backend/.env into os.environ, so a developer's
    # real Tavily key would otherwise send test searches to the paid API.
    # Tests that exercise Tavily set a fake key and stub the HTTP client.
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    # Retrieval tests run keyword-only: never download or load the local
    # embedding model in a test run.
    monkeypatch.setenv("EMBEDDING_PROVIDER", "none")
    # Claim verification calls a live model; tests that cover it stub it.
    monkeypatch.setenv("CLAIM_VERIFICATION", "off")
    # Tests of semantic retrieval/coverage explicitly enable and stub them.
    monkeypatch.setenv("EVIDENCE_PLANNING", "off")
    # A developer's local .env may skip the setup-fingerprint check for a
    # shared database; tests always run with the production behaviour.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "SKIP_STARTUP_FINGERPRINT_CHECK", False)
    # The health sampler probes live services; never from a test's app lifespan.
    monkeypatch.setattr(get_settings(), "HEALTH_SAMPLER_ENABLED", False)
    # The GOV.UK search fallback is a live API; tests that cover it stub it.
    from app.orchestration import websearch

    async def _no_govuk(query):
        return []
    monkeypatch.setattr(websearch, "_govuk_results", _no_govuk)
    # The official IFRS standards are a live download; tests that cover it stub it.
    from app.orchestration import official_standards

    async def _no_standard(code):
        return ""
    monkeypatch.setattr(official_standards, "_download_standard", _no_standard)
    official_standards._standard_cache.clear()
    from app.domains.source_library.embeddings import get_embedder

    get_embedder.cache_clear()


@pytest.fixture(autouse=True)
def _block_live_http(request, monkeypatch):
    """No offline test reaches a real website. The per-service stubs above
    missed govuk.py's own search, so a prompt-size test grew from about 2,300
    to 8,545 characters when GOV.UK's page changed (22 Oct 2026), and two more
    test files were reading GOV.UK, DBnomics and Frankfurter live. Mock
    transports and loopback servers are unaffected; tests marked live or
    integration keep the network."""
    import os

    if os.getenv("RUN_LIVE_HTTP_TESTS") == "1" or request.node.get_closest_marker("live") \
            or request.node.get_closest_marker("integration"):
        return
    import httpx

    def offline(self, http_request):
        if http_request.url.host in ("localhost", "127.0.0.1", "::1"):
            return original_sync(self, http_request)
        raise httpx.ConnectError(f"Live HTTP is disabled in offline tests: {http_request.url.host}",
                                 request=http_request)

    async def offline_async(self, http_request):
        if http_request.url.host in ("localhost", "127.0.0.1", "::1"):
            return await original_async(self, http_request)
        raise httpx.ConnectError(f"Live HTTP is disabled in offline tests: {http_request.url.host}",
                                 request=http_request)

    original_sync = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", offline)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", offline_async)


@pytest.fixture(autouse=True)
def _fresh_in_process_caches():
    # Process-level caches must not carry one test's users into another.
    from app.domains.identity import governance
    from app.domains.notifications_workflow import service as notifications

    governance.forget_break_glass_cache()
    notifications._action_cache.clear()
    notifications._last_sync.clear()
    yield
