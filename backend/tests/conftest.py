import pytest


@pytest.fixture(autouse=True)
def _no_paid_search_api(monkeypatch):
    # app/core/config.py loads backend/.env into os.environ, so a developer's
    # real Tavily key would otherwise send test searches to the paid API.
    # Tests that exercise Tavily set a fake key and stub the HTTP client.
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
