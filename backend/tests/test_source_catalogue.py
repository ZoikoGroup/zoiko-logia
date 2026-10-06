"""
The source catalogue widens the trusted-domain allowlist to more countries and
bodies. It must only ADD domains after the taxonomy's own, route a question to
the country it names, and stay small per question. Pure and offline.
"""
import re

from app.orchestration.source_catalogue import (
    _CATALOGUE,
    MAX_CATALOGUE_DOMAINS,
    catalogue_domains,
    detect_catalogue_jurisdictions,
)
from app.orchestration.source_taxonomy import (
    ALL_TOPICS,
    ECONOMY,
    TAX,
    allowed_domains,
    detect_topics,
    site_filter,
)

_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def _domains_for(query: str, jurisdiction: str = "") -> list[str]:
    return allowed_domains(jurisdiction, detect_topics(query), query)


# ── the catalogue itself ─────────────────────────────────────────────────

def test_every_entry_is_a_bare_domain_under_a_known_topic():
    for key, topics in _CATALOGUE.items():
        for topic, domains in topics.items():
            assert topic in ALL_TOPICS, (key, topic)
            for d in domains:
                assert _DOMAIN.match(d), (key, d)


# ── routing a question to the country it names ──────────────────────────

def test_ireland_tax_question_reaches_irish_revenue():
    domains = _domains_for("What is Ireland's corporation tax rate?")
    assert "revenue.ie" in domains
    # Economy-only bodies have no authority over a tax rate.
    assert "cso.ie" not in domains


def test_country_economy_question_reaches_its_central_bank():
    assert "bcb.gov.br" in _domains_for("What is the inflation rate in Brazil?")
    assert "resbank.co.za" in _domains_for("South Africa repo rate")
    assert "boj.or.jp" in _domains_for("Japan interest rate")


def test_comparison_reaches_every_country_named():
    domains = _domains_for("Compare inflation in Canada and Australia")
    assert "bankofcanada.ca" in domains and "abs.gov.au" in domains


def test_country_with_nothing_for_the_topic_adds_nothing():
    # Brazil has no tax body listed, so the allowlist is the taxonomy's alone.
    query = "What is Brazil's VAT rate?"
    assert catalogue_domains(["GLOBAL"], detect_topics(query), query) == []


def test_word_boundaries_guard_country_names():
    # "oman" inside "woman" and "peru" inside "perusal" are not countries.
    assert detect_catalogue_jurisdictions("a woman's perusal of the report") == []


def test_south_africa_comes_before_the_africa_region():
    assert detect_catalogue_jurisdictions("South Africa GDP")[:2] == ["SOUTH_AFRICA", "AFRICA"]


# ── only adds, never reorders, stays small ───────────────────────────────

def test_taxonomy_domains_keep_their_place_ahead_of_the_catalogue():
    domains = allowed_domains("UK", {ECONOMY})
    assert domains[:3] == ["worldbank.org", "imf.org", "oecd.org"]
    assert domains.index("ons.gov.uk") < domains.index("dmo.gov.uk")


def test_site_bias_for_existing_jurisdictions_is_unchanged():
    # The catalogue appends after the taxonomy, so the first eight domains
    # the site: clause uses for a UK tax question stay the taxonomy's.
    assert "dmo.gov.uk" not in site_filter(allowed_domains("UK", {TAX}))


def test_off_taxonomy_question_is_not_widened_with_global_bodies():
    assert catalogue_domains(["GLOBAL"], set(), "Who founded the company?") == []


def test_catalogue_additions_are_capped_per_question():
    query = "Compare GDP in Brazil, Mexico, Chile, Peru, Colombia and Argentina"
    assert len(catalogue_domains(["GLOBAL"], detect_topics(query), query)) <= MAX_CATALOGUE_DOMAINS
