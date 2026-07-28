from app.domains.reference_data.adapters.professional_search_adapter import is_allowed_authority_url


def test_authority_url_allowlist_accepts_domains_and_subdomains():
    allowed = ["irs.gov", "pcaobus.org"]
    assert is_allowed_authority_url("https://www.irs.gov/publications/p15", allowed)
    assert is_allowed_authority_url("https://pcaobus.org/standards", allowed)


def test_authority_url_allowlist_rejects_spoofing_and_insecure_urls():
    allowed = ["irs.gov"]
    assert not is_allowed_authority_url("https://irs.gov.example.com/fake", allowed)
    assert not is_allowed_authority_url("https://evil-irs.gov/fake", allowed)
    assert not is_allowed_authority_url("http://irs.gov/insecure", allowed)
