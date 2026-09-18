"""
Regression suite for the topic-aware authoritative-source taxonomy and the
organisation spread that consumes it.

Two separable concerns are covered here:

  1. source_taxonomy.py — policy. Which bodies have authority over a given
     jurisdiction x topic, and does a URL genuinely belong to one of them.
  2. websearch.py's _spread_across_organisations — retrieval shape. Five hits
     from one body must not occupy all five citation slots while a
     standard-setter that also answered goes unshown.

Pure and offline: no SearXNG instance and no network are involved.
"""
from app.orchestration.source_taxonomy import (
    ACCOUNTING,
    AUDIT,
    ECONOMY,
    PAYROLL,
    TAX,
    allowed_domains,
    detect_topics,
    matches_allowlist,
    organisation_key,
    site_filter,
)
from app.orchestration.websearch import WebSource, _spread_across_organisations


# ── topic detection ──────────────────────────────────────────────────────

def test_tax_question_detects_tax_topic():
    assert detect_topics("What is the UK VAT threshold?") == {TAX}


def test_audit_standard_detects_audit_topic():
    assert detect_topics("ISA 315 risk assessment") == {AUDIT}


def test_payroll_question_detects_payroll_topic():
    assert detect_topics("PAYE RTI submission deadline") == {PAYROLL}


def test_macro_indicator_detects_economy_not_tax():
    # A GDP figure comes from a statistics agency, not a tax authority.
    assert detect_topics("India GDP growth rate") == {ECONOMY}


def test_a_question_may_span_several_topics():
    assert {PAYROLL, TAX, AUDIT} <= detect_topics("payroll tax audit obligations")


def test_word_boundaries_guard_against_substring_matches():
    # "vat" must not fire on "private"; "isa" must not fire on "Isaac".
    assert TAX not in detect_topics("private company records")
    assert AUDIT not in detect_topics("Isaac joined the firm")


def test_off_taxonomy_question_detects_nothing():
    assert detect_topics("Who founded the company?") == set()


# ── domain resolution ────────────────────────────────────────────────────

def test_topic_narrows_the_jurisdiction_list():
    tax_domains = allowed_domains("UK", {TAX})
    assert "hmrc.gov.uk" in tax_domains
    # An audit-only body has no authority over a VAT threshold question.
    assert "iaasb.org" not in tax_domains


def test_global_bodies_are_always_included():
    assert "ifrs.org" in allowed_domains("INDIA", {ACCOUNTING})


def test_no_topics_falls_back_to_the_whole_jurisdiction():
    # The behaviour the jurisdiction-only allowlist had before topics existed.
    every = allowed_domains("UK")
    assert {"hmrc.gov.uk", "frc.org.uk", "ons.gov.uk"} <= set(every)


def test_regional_jurisdiction_resolves_to_its_country():
    assert allowed_domains("US-CA", {TAX}) == allowed_domains("US", {TAX})


# ── allowlist matching ───────────────────────────────────────────────────

def test_subdomain_of_an_allowed_domain_matches():
    assert matches_allowlist("https://www.gov.uk/vat-rates", ["gov.uk"])


def test_lookalike_host_is_rejected():
    # The substring test this replaced accepted both of these.
    assert not matches_allowlist("https://gov.uk.example.com/vat", ["gov.uk"])
    assert not matches_allowlist("https://evil.com/?q=irs.gov", ["irs.gov"])


# ── organisation grouping ────────────────────────────────────────────────

def test_one_government_is_one_organisation():
    domains = allowed_domains("UK")
    keys = {
        organisation_key(url, domains)
        for url in (
            "https://www.gov.uk/vat",
            "https://hmrc.gov.uk/manual",
            "https://www.legislation.gov.uk/ukpga/1994",
        )
    }
    assert keys == {"gov.uk"}


def test_off_allowlist_hosts_group_on_bare_hostname():
    assert organisation_key("https://www.example.com/a", []) == "example.com"
    assert organisation_key("https://example.com/b", []) == "example.com"


# ── the spread itself ────────────────────────────────────────────────────

def _sources(*urls):
    return [WebSource(title=u, url=u, snippet="") for u in urls]


def test_distinct_bodies_are_returned_before_any_body_repeats():
    domains = allowed_domains("UK")
    spread = _spread_across_organisations(
        _sources(
            "https://www.gov.uk/manual/p1",
            "https://www.gov.uk/manual/p2",
            "https://www.gov.uk/manual/p3",
            "https://www.frc.org.uk/standards",
            "https://www.icaew.com/guidance",
        ),
        domains,
        limit=3,
    )
    assert [organisation_key(s.url, domains) for s in spread] == [
        "gov.uk", "frc.org.uk", "icaew.com",
    ]


def test_engine_ranking_still_decides_which_page_represents_a_body():
    domains = allowed_domains("UK")
    spread = _spread_across_organisations(
        _sources("https://www.gov.uk/first", "https://www.gov.uk/second"), domains, limit=1,
    )
    assert spread[0].url.endswith("/first")


def test_a_single_body_is_still_returned_rather_than_truncated():
    # Spreading must never cost the user sources when only one body answered.
    domains = allowed_domains("UK")
    urls = ["https://www.gov.uk/p1", "https://www.gov.uk/p2", "https://www.gov.uk/p3"]
    spread = _spread_across_organisations(_sources(*urls), domains, limit=5)
    assert [s.url for s in spread] == urls


def test_spread_never_exceeds_the_limit():
    domains = allowed_domains("UK")
    spread = _spread_across_organisations(
        _sources(*[f"https://www.body{i}.com/p" for i in range(20)]), domains, limit=4,
    )
    assert len(spread) == 4


def test_empty_input_spreads_to_nothing():
    assert _spread_across_organisations([], allowed_domains("UK"), limit=5) == []


# ── site: bias ───────────────────────────────────────────────────────────

def test_site_filter_biases_retrieval_toward_the_resolved_bodies():
    clause = site_filter(allowed_domains("UK", {PAYROLL}))
    assert clause.startswith("(") and clause.endswith(")")
    assert "site:cipp.org.uk" in clause


def test_site_filter_is_capped_so_engines_do_not_drop_the_query():
    assert site_filter([f"body{i}.com" for i in range(50)]).count("site:") <= 8


def test_site_filter_is_empty_when_there_is_nothing_to_bias_with():
    # Callers concatenate unconditionally, so this must be "" not None.
    assert site_filter([]) == ""
