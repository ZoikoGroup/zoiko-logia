import pytest


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
    from app.domains.source_library.embeddings import get_embedder

    get_embedder.cache_clear()
