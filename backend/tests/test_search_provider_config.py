from app.core.config import Settings


def test_professional_search_provider_defaults_are_safe():
    settings = Settings(_env_file=None)

    assert settings.TAVILY_API_BASE_URL == "https://api.tavily.com"
    assert settings.SERP_API_BASE_URL == "https://serpapi.com/search.json"
    assert "irs.gov" in settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS
    assert "pcaobus.org" in settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS
    assert "congress.gov" in settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS
    assert all(not domain.startswith("http") for domain in settings.PROFESSIONAL_SEARCH_ALLOWED_DOMAINS)
