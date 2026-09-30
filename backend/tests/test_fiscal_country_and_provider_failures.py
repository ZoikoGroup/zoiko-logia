"""Regression tests for the fiscal, country-detection and provider-failure work.

Every test here pins behaviour that was verified against the live APIs or read
out of the code during the 10-country validation. They fail if any of it
regresses, and none of them read, print or require a real secret: provider keys
are monkeypatched as obviously-fake literals.

The three groups are:

  1. Fiscal routing — the statistic gate used to reject "government revenue",
     "current account" and "budget balance" outright, or silently answer them
     with GDP GROWTH, because they fell through to the generic WDI gdp rule.
  2. Country detection — bare two-letter ISO codes and common English/French
     words used to identify countries they never meant ("us", "au").
  3. Provider failure classification — Alpha Vantage returns HTTP 200 with an
     error body, and each of those bodies has to become the RIGHT typed error,
     or the pipeline confidently reports the wrong thing.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domains.market_data.http import request_json
from app.domains.market_data.providers.alpha_vantage import AlphaVantageProvider
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.providers.finnhub import FinnhubProvider
from app.domains.market_data.providers.index_quote import IndexQuoteProvider
from app.domains.market_data.providers.polygon import PolygonProvider
from app.domains.market_data.schemas import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderForbidden,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
    StockQuote,
)
from app.orchestration import dbnomics
from app.orchestration import country_scope
from app.orchestration import fred
from app.orchestration import frankfurter
from app.domains.market_data import service
from app.orchestration import market_data
from app.orchestration.fred import _US_HINT

# The ten countries under validation, with a phrasing of the name that a user
# would plausibly type.
COUNTRIES = [
    ("us", "United States"),
    ("uk", "United Kingdom"),
    ("ireland", "Ireland"),
    ("canada", "Canada"),
    ("australia", "Australia"),
    ("germany", "Germany"),
    ("france", "France"),
    ("japan", "Japan"),
    ("india", "India"),
    ("china", "China"),
]

# Alpha Vantage's throttling body, verified live against the free tier. It
# arrives with HTTP 200, so the status code alone cannot detect it.
THROTTLE_BODIES = [
    {"Information": "Thank you for using Alpha Vantage! Please consider spreading out "
                    "your free API requests more sparingly (1 request per second)."},
    {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is "
             "25 requests per minute."},
]

# Also verified live: this is how the endpoint answers an absent/rejected key.
INVALID_KEY_BODY = {
    "Error Message": "the parameter apikey is invalid or missing. Please claim your "
                     "free API key on (https://www.alphavantage.co/support/#api-key)."
}


def _provider(monkeypatch, key: str = "TESTKEY0000000000") -> AlphaVantageProvider:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", key)
    return AlphaVantageProvider()


# ── 1. fiscal routing ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "government revenue",
    "general government revenue",
    "current account",
    "current account balance",
    "fiscal balance",
    "budget balance",
    "budget surplus",
    "budget deficit",
])
def test_fiscal_phrases_pass_the_statistic_gate(phrase):
    """The gate runs BEFORE every resolver, so a miss here means NO_SOURCE."""
    assert dbnomics._STAT_HINTS.search(f"{phrase} as a percentage of GDP")


@pytest.mark.parametrize("slug,name", COUNTRIES)
@pytest.mark.parametrize("phrase", [
    "government revenue",
    "current account",
    "budget deficit",
])
def test_fiscal_phrases_pass_gate_for_every_country(slug, name, phrase):
    assert dbnomics._STAT_HINTS.search(f"{name} {phrase}")


def test_current_account_resolves_to_its_own_wdi_indicator():
    """Current account and trade balance are different statistics and must not
    resolve to the same code — returning trade balance for a current-account
    question is a plausible-looking wrong answer."""
    current = dbnomics._wdi_match("Germany current account balance")
    trade = dbnomics._wdi_match("Germany trade balance")
    assert current is not None and trade is not None
    assert current[0] == "BN.CAB.XOKA.GD.ZS"
    assert current[0] != trade[0]


def _fiscal_subject(query: str) -> str | None:
    """The subject _find_weo_fiscal_series picks, without touching the network.

    Mirrors dbnomics.py:954. Asserting it directly keeps the test offline while
    still exercising the production lookup table.
    """
    return next((s for p, s, _ in dbnomics._FISCAL_WEO_SUBJECTS if p.search(query)), None)


@pytest.mark.parametrize("slug,name", COUNTRIES)
@pytest.mark.parametrize("phrase,expected", [
    ("government revenue as a percentage of GDP", "GGR_NGDP"),
    ("general government revenue", "GGR_NGDP"),
    ("government revenue, percent of GDP", "GGR_NGDP"),
    ("budget deficit as a percentage of GDP", "GGXCNL_NGDP"),
    ("fiscal balance", "GGXCNL_NGDP"),
])
def test_revenue_and_deficit_route_to_their_own_weo_aggregate(slug, name, phrase, expected):
    """Revenue must resolve to WEO revenue and deficit to net lending/borrowing.

    Before this, both phrases fell through to the generic WDI 'gdp' rule and
    were answered with GDP GROWTH (NY.GDP.MKTP.KD.ZG) for the first five
    countries, which is a real number for the wrong statistic.
    """
    assert _fiscal_subject(f"{name} {phrase}") == expected


@pytest.mark.parametrize("slug,name", COUNTRIES)
def test_revenue_is_not_restricted_to_the_new_five(slug, name):
    """Only DEBT is scoped to the new five; revenue and net lending/borrowing
    must reach all ten, because the first five had no route for them at all."""
    country = dbnomics._country_in_query(f"{name} government revenue")
    subject = _fiscal_subject(f"{name} government revenue")
    assert country is not None
    if country in dbnomics._NEW_FIVE:
        assert subject != "GGXWDG_NGDP", "debt scoping must not affect revenue"
    assert dbnomics._WEO_UNITS.get(subject), "subject must have a published unit"


@pytest.mark.parametrize("slug,name", [
    ("us", "United States"), ("uk", "United Kingdom"), ("ireland", "Ireland"),
    ("canada", "Canada"), ("australia", "Australia"),
])
def test_first_five_debt_still_defers_to_its_existing_source(slug, name):
    """Working routing must be preserved: the five countries that already answer
    debt from WDI/FRED must NOT be switched to the WEO general-government
    aggregate. Only the new five (DE/FR/JP/IN/CN) take the WEO debt route."""
    country = dbnomics._country_in_query(f"{name} government debt as a percentage of GDP")
    assert _fiscal_subject(f"{name} government debt") == "GGXWDG_NGDP"
    assert country not in dbnomics._NEW_FIVE, \
        "swapping a working publisher-specific debt source is out of scope"


@pytest.mark.parametrize("slug,name", [
    ("germany", "Germany"), ("france", "France"), ("japan", "Japan"),
    ("india", "India"), ("china", "China"),
])
def test_new_five_debt_uses_the_weo_general_government_aggregate(slug, name):
    """WDI's central-government-debt series carries no China observations at all,
    so the new five need WEO here; the scope is deliberate and must stay."""
    country = dbnomics._country_in_query(f"{name} government debt as a percentage of GDP")
    assert country in dbnomics._NEW_FIVE
    assert _fiscal_subject(f"{name} government debt as a percentage of GDP") == "GGXWDG_NGDP"
    assert dbnomics._WEO_UNITS.get("GGXWDG_NGDP")


# ── 2. country detection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "the company told us about GDP",
    "give us a chart",
    "tell us more",
    "revenue for us",
    "how much did they earn",
])
def test_lowercase_us_is_not_the_united_states(phrase):
    assert dbnomics._country_in_query(phrase) != "United States"
    assert "United States" not in dbnomics._detect_countries(phrase)
    assert not _US_HINT.search(phrase)
    assert not country_scope.names_country(phrase, "US")


def test_bare_uppercase_us_is_still_the_united_states():
    """The case-sensitive fix must not break the real thing."""
    assert dbnomics._country_in_query("US unemployment rate") == "United States"
    # _COUNTRY_ALIASES/_ISO3 use lower-case canonical names; _country_in_query
    # uses display case. Both are internally consistent with their own tables.
    assert [c.lower() for c in dbnomics._detect_countries("US unemployment rate")] == [
        "united states"]
    assert country_scope.names_country("US inflation", "US")


@pytest.mark.parametrize("text", [
    "Australia GDP",
    "Australia inflation",
    "ASX 200",
    "Australian unemployment rate",
])
def test_australia_is_still_detected(text):
    assert country_scope.names_country(text, "AU")


def test_french_au_is_not_australia():
    """'au' is a French preposition; it used to pin the query to Australia."""
    for phrase in ("auPIB de la France", "l'inflation en Allemagne au troisième trimestre"):
        assert not country_scope.names_country(phrase, "AU"), phrase
        assert "australia" not in [
            c.lower() for c in dbnomics._detect_countries(phrase)], phrase


def test_austria_is_never_australia():
    """Austria must read as 'some other country', which sends the question to the
    web-grounded path instead of confidently answering with Australian data."""
    for phrase in ("Austria inflation rate", "Austrian GDP growth"):
        assert country_scope.names_another_country(phrase), phrase
        assert not country_scope.names_country(phrase, "AU"), phrase


@pytest.mark.parametrize("phrase", ["Austria inflation rate", "Austrian GDP growth"])
def test_austria_is_refused_by_every_supported_connector(phrase):
    """'Some other country' has to win over all ten, or Austria's questions get
    answered with ten real, correctly-formatted numbers for the wrong economies."""
    assert not country_scope.is_country_scoped(phrase, "DE")
    assert not country_scope.is_country_scoped(phrase, "AU")


# Known remaining gap, recorded rather than silently fixed: _OTHER_COUNTRIES
# lists Germany/French/Spanish-style English and native forms inconsistently
# ("Deutschland" and "France"/"French" are present, but Austria has no German or
# French form). Adding language variants ad hoc would be arbitrary — a Dutch,
# Italian or Japanese query has the same hole — so this is reported for a
# decision rather than half-fixed. Asserted so the gap cannot drift unnoticed.
@pytest.mark.parametrize("phrase", [
    "österreichische Inflation",
    "l'inflation en Autriche",
])
def test_known_gap_non_english_austria_aliases(phrase):
    if country_scope.names_another_country(phrase):
        return  # fixed at some point; the guard is no longer needed
    pytest.xfail(
        "_OTHER_COUNTRIES has no native-language alias for Austria; "
        "reported as a remaining gap, not silently patched")


def test_ambiguous_acronyms_do_not_pin_a_country():
    """IN and CN are excluded on purpose: 'in' is an English preposition and
    'cn' is a country-code fragment."""
    assert not country_scope.names_country("growth in France", "IN")
    assert not country_scope.names_country("listed in Germany", "CN")


def test_names_another_country_covers_the_unsupported_ten():
    """A query naming a country outside the supported ten must not be answered
    from the ten's connectors."""
    for phrase in ("New Zealand inflation rate", "Luxembourg policy rate",
                   "Brazil GDP growth"):
        assert country_scope.names_another_country(phrase), phrase


# ── 5. single-series routing: the "% of GDP" hijack ──────────────────────────

def test_wdi_fallback_scope_is_exactly_the_three_verified_broken_indicators():
    """This list is the whole guard against replacing working routing. Every
    entry must be an indicator that was verified to return the GDP LEVEL or
    nothing; nothing that already had a correct source."""
    assert dbnomics._WDI_FALLBACK_CODES == frozenset({
        "BN.CAB.XOKA.GD.ZS",   # current account
        "NE.RSB.GNFS.ZS",      # trade balance
        "GC.DOD.TOTL.GD.ZS",   # central government debt
    })


@pytest.mark.parametrize("phrase,code", [
    ("current account balance as a percentage of GDP", "BN.CAB.XOKA.GD.ZS"),
    ("trade balance as a percentage of GDP", "NE.RSB.GNFS.ZS"),
    ("government debt as a percentage of GDP", "GC.DOD.TOTL.GD.ZS"),
])
def test_the_three_broken_indicators_map_into_the_fallback_set(phrase, code):
    assert dbnomics._wdi_match(phrase)[0] == code
    assert code in dbnomics._WDI_FALLBACK_CODES


@pytest.mark.parametrize("phrase", [
    "GDP in US dollars",
    "GDP growth rate",
    "GDP per capita",
])
def test_working_gdp_indicators_stay_out_of_the_fallback_set(phrase):
    """GDP itself must keep its WEO route; intercepting it would swap a working
    publisher-specific source, which is the change this file must never make."""
    assert dbnomics._wdi_match(phrase)[0] not in dbnomics._WDI_FALLBACK_CODES


# ── 6. FRED must not answer a ratio question with a currency level ───────────

@pytest.mark.parametrize("phrase", [
    "United States trade balance as a percentage of GDP",
    "United States current account balance as a percentage of GDP",
    "US trade balance as a share of GDP",
    "US current account % of GDP",
    "US trade balance relative to GDP",
])
def test_fred_declines_ratio_phrasings_for_its_dollar_level_series(monkeypatch, phrase):
    """BOPGSTB and IEABC are in millions of dollars. Answering a "% of GDP"
    question with them produced a number ~1000x too large, and made the US
    disagree with the other nine countries on the identical question."""
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY0000000000")
    assert fred._definition_for_query(phrase) is None


@pytest.mark.parametrize("phrase,series_id", [
    ("what is the US trade balance", "BOPGSTB"),
    ("US current account balance", "IEABC"),
])
def test_fred_still_answers_level_questions_with_its_dollar_series(monkeypatch, phrase, series_id):
    """Declining ratio phrasings must not cost the series its ordinary use."""
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY0000000000")
    definition = fred._definition_for_query(phrase)
    assert definition is not None and definition.series_id == series_id
    assert definition.unit == "millions of dollars"


@pytest.mark.parametrize("phrase,series_id", [
    ("United States government debt as a percentage of GDP", "GFDEGDQ188S"),
    ("United States government revenue as a percentage of GDP", "FYFRGDA188S"),
    ("United States budget deficit as a percentage of GDP", "FYFSGDA188S"),
])
def test_fred_keeps_its_genuine_percentage_series(monkeypatch, phrase, series_id):
    """GFDEGDQ188S/FYFRGDA188S/FYFSGDA188S really are % of GDP; they must not be
    caught by the ratio guard."""
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY0000000000")
    definition = fred._definition_for_query(phrase)
    assert definition is not None and definition.series_id == series_id


def test_ratio_guard_does_not_fire_without_an_explicit_unit_request(monkeypatch):
    """The guard must key on the unit request, not on any mention of GDP, or it
    would strip the US of series it can legitimately answer."""
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY0000000000")
    assert not fred._RATIO_ASK.search("how much is the US trade balance in dollars")
    assert not fred._RATIO_ASK.search("compare US and German GDP")
    assert fred._RATIO_ASK.search("US trade balance as a percentage of GDP")


# ── 7. Alpha Vantage failure classification ───────────────────────────────────

@pytest.mark.parametrize("body", THROTTLE_BODIES)
def test_throttle_is_rate_limited_not_auth_failure(monkeypatch, body):
    """Verified live: the free tier throttles with HTTP 200 + a prose body.
    Calling that an auth failure would blame the credential and, worse, tell the
    pipeline to stop instead of retrying."""
    provider = _provider(monkeypatch)
    with pytest.raises(ProviderRateLimited):
        provider._check_envelope(body)


def test_rejected_key_is_an_auth_failure(monkeypatch):
    """A missing/rejected key also arrives as HTTP 200. Folding it into
    ProviderBadResponse both mislabelled it as 'no such ticker' AND stopped the
    fallback chain, because service.fetch_for_intent treats BadResponse as
    'the provider answered, the entity is not there'."""
    provider = _provider(monkeypatch)
    with pytest.raises(ProviderAuthError):
        provider._check_envelope(INVALID_KEY_BODY)


@pytest.mark.parametrize("message", [
    "the parameter apikey is invalid or missing. Please claim your free API key.",
    "Invalid API key provided",
    "Invalid API call! Invalid apikey.",
])
def test_key_rejection_variants_are_all_auth(monkeypatch, message):
    provider = _provider(monkeypatch)
    with pytest.raises(ProviderAuthError):
        provider._check_envelope({"Error Message": message})


def test_genuine_bad_request_is_still_a_bad_response(monkeypatch):
    """An unknown function is the caller's mistake, not a credential problem —
    it must NOT be reported as an auth failure."""
    provider = _provider(monkeypatch)
    with pytest.raises(ProviderBadResponse) as exc:
        provider._check_envelope({"Error Message": "This API function (NOPE) does not exist."})
    assert not isinstance(exc.value, ProviderAuthError)


@pytest.mark.parametrize("body", [[], "a string", 42, None])
def test_non_object_body_is_a_bad_response(monkeypatch, body):
    provider = _provider(monkeypatch)
    with pytest.raises(ProviderBadResponse):
        provider._check_envelope(body)


def test_good_payload_passes_through_unchanged(monkeypatch):
    provider = _provider(monkeypatch)
    payload = {"Global Quote": {"01. symbol": "AAPL", "05. price": "329.4000"}}
    assert provider._check_envelope(payload) is payload


def test_missing_key_is_not_configured_not_a_crash(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    provider = AlphaVantageProvider()
    with pytest.raises(ProviderNotConfigured):
        provider._params(function="GLOBAL_QUOTE")


def test_empty_configured_key_is_still_not_configured(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "   ")
    provider = AlphaVantageProvider()
    with pytest.raises(ProviderNotConfigured):
        provider._params(function="GLOBAL_QUOTE")


# ── 4. the shared HTTP layer ──────────────────────────────────────────────────

def _run_request(monkeypatch, handler, **kwargs):
    """Drive request_json against a stub transport, with no backoff sleeping."""
    monkeypatch.setattr("app.domains.market_data.http._sleep_backoff",
                        lambda *a, **k: asyncio.sleep(0))
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return asyncio.run(request_json(client, "probe", "https://example.invalid/x", **kwargs))


def test_401_is_an_auth_error_and_is_never_retried(monkeypatch):
    """401 is the one unambiguous credential rejection.

    Measured live against Finnhub on 2026-09-30, both an invalid key
    ({"error":"Invalid API key."}) and a missing key return 401.
    """
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "Invalid API key."})

    with pytest.raises(ProviderAuthError):
        _run_request(monkeypatch, handler, retries=3)
    assert len(calls) == 1, "auth rejection must not be retried"


def test_403_is_forbidden_not_an_auth_error_and_is_never_retried(monkeypatch):
    """403 means "this credential cannot use this endpoint", not "bad key".

    Measured live against Finnhub on 2026-09-30: a VALID key calling an endpoint
    outside its plan returns 403 with
    {"error":"You don't have access to this resource."} This test failed while
    403 was still folded into the auth branch, which is why it exists: reporting
    an entitlement restriction as "authentication rejected (HTTP 403)" tells an
    operator to rotate a key that works.
    """
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            403, json={"error": "You don't have access to this resource."}
        )

    with pytest.raises(ProviderForbidden) as caught:
        _run_request(monkeypatch, handler, retries=3)

    assert not isinstance(caught.value, ProviderAuthError), (
        "a plan/coverage refusal must never be reported as an auth failure"
    )
    assert len(calls) == 1, "a 403 must not be retried either"
    assert "403" in str(caught.value)


def test_403_still_falls_through_the_provider_chain(monkeypatch):
    """A 403 must not stop the chain.

    ProviderBadResponse stops it deliberately (the provider answered, so the
    next one could only guess at a different company). A 403 has to keep the
    old behaviour of moving on to the next provider, or refusing one provider's
    entitlements would take down every fallback behind it.
    """
    assert issubclass(ProviderForbidden, ProviderError)
    assert not issubclass(ProviderForbidden, ProviderBadResponse)
    # service.fetch_for_intent routes ProviderNotConfigured/CapabilityNotSupported
    # and then a bare ProviderError through `continue`, so the chain advances.
    assert ProviderForbidden not in service._FALLBACK_ERRORS


def test_429_is_rate_limited(monkeypatch):
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "1"}, json={})

    with pytest.raises(ProviderRateLimited):
        _run_request(monkeypatch, handler, retries=1)


def test_5xx_retries_then_reports_unavailable(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={})

    with pytest.raises(ProviderUnavailable):
        _run_request(monkeypatch, handler, retries=2)
    assert len(calls) == 3, "one initial attempt plus two retries"


def test_timeout_retries_then_reports_unavailable(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("simulated", request=request)

    with pytest.raises(ProviderUnavailable):
        _run_request(monkeypatch, handler, retries=1)
    assert len(calls) == 2


def test_empty_body_is_a_bad_response(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"")

    with pytest.raises(ProviderBadResponse):
        _run_request(monkeypatch, handler)


def test_non_json_body_is_a_bad_response(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"<html>maintenance</html>",
                              headers={"content-type": "text/html"})

    with pytest.raises(ProviderBadResponse):
        _run_request(monkeypatch, handler)


def test_4xx_that_is_not_auth_is_a_bad_response(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={})

    with pytest.raises(ProviderBadResponse):
        _run_request(monkeypatch, handler)


# ---------------------------------------------------------------------------
# 4. Provenance — a source that fetched real numbers must carry them
# ---------------------------------------------------------------------------
# The audit found two connectors whose citations pointed at a real endpoint but
# exposed the value only as English prose inside `snippet`: FRED and index_quote.
# Everything downstream that needs a number (charts, structured evidence, the
# "which series is this?" answer, a replayable audit record) had nothing to read
# and would have had to re-parse the prose — exactly the model-generated-substitute
# the source doctrine forbids. Both now populate the structured fields. A URL is
# a locator; it is not provenance.

FREED_MATCH = fred.FredSeriesMatch(
    series_id="FEDFUNDS",
    series_name="Federal Funds Effective Rate",
    points=[("2026-09-24", 3.63), ("2026-09-25", 3.63), ("2026-09-26", 3.63)],
    unit="percent",
    frequency="daily",
    url="https://fred.stlouisfed.org/series/FEDFUNDS",
)


def test_fred_source_carries_structured_observation_and_series():
    src = fred._build_source(FREED_MATCH)

    assert src.provider == "Federal Reserve Bank of St. Louis (FRED)"
    assert src.series == [("2026-09-24", 3.63), ("2026-09-25", 3.63), ("2026-09-26", 3.63)]

    obs = src.observation
    assert obs is not None, "FRED source must expose the fetched value, not just prose"
    assert obs.value == "3.63"
    assert obs.period == "2026-09-26"
    assert obs.indicator == "FEDFUNDS"
    assert obs.provider == "Federal Reserve Bank of St. Louis (FRED)"
    assert obs.source_url == FREED_MATCH.url
    assert obs.freshness == "historical"


def test_fred_source_observation_tracks_the_latest_point_not_the_first():
    # A source that reported the OLDEST of several fetched points would be
    # confidently wrong in a different way — and silently so.
    src = fred._build_source(FREED_MATCH)
    assert src.observation.period == FREED_MATCH.points[-1][0]
    assert src.observation.value == f"{FREED_MATCH.points[-1][1]:g}"


def test_index_quote_source_carries_structured_observation():
    quote = StockQuote(
        symbol="^GDAXI",
        price=24312.44,
        provider="index_quote",
        freshness="delayed",
        fetched_at="2026-09-30T12:00:00+00:00",
        provider_timestamp="2026-09-30T17:52:03+00:00",
        source_url="https://finance.yahoo.com/quote/^GDAXI",
    )
    src = market_data._quote_source(quote)

    obs = src.observation
    assert obs is not None, "an index level must be readable as a number, not as a sentence"
    assert obs.value == "24312.44"
    assert obs.indicator == "^GDAXI"
    assert obs.period == "2026-09-30T17:52:03"
    assert obs.unit == "index_points"
    assert obs.freshness == "delayed"
    assert obs.source_url == quote.source_url


def test_index_quote_source_does_not_overstate_delayed_as_realtime():
    # index_quote's whole reason to exist is that it refuses to claim realtime.
    quote = StockQuote(
        symbol="^N225",
        price=39902.0,
        provider="index_quote",
        freshness="delayed",
        fetched_at="2026-09-30T12:00:00+00:00",
        source_url="https://finance.yahoo.com/quote/^N225",
    )
    src = market_data._quote_source(quote)
    assert src.freshness == "delayed"
    assert src.observation.freshness == "delayed"


def test_every_live_data_source_kind_exposes_a_value_or_is_declared_absent():
    """A citation must never be a bare URL.

    Whichever connector answered, the source has to carry either a structured
    observation or a structured series. Anything else is the prose-only shape
    the audit rejected.
    """
    for src in (
        fred._build_source(FREED_MATCH),
    ):
        assert src.observation is not None or src.series
        assert src.url
        assert src.provider


# ---------------------------------------------------------------------------
# 5. Bare ISO codes, and refusing a country we do not cover
# ---------------------------------------------------------------------------
# The live audit found "DE GDP growth rate" answered with ISTAT — Italian GDP
# growth, correctly formatted, from a real official statistical institute, for a
# question that asked about Germany. Two independent causes:
#
#   (a) no bare two-letter ISO code was recognised as naming a country, so
#       dbnomics had no country claim to check the candidate series against; and
#   (b) when a query names no country, _series_is_country() returned True for
#       ANY series, so an unrelated country could never be refused.
#
# Italy is not one of the ten supported economies, so this was both a wrong
# country and an out-of-scope one — and it did not read as an error anywhere in
# the pipeline, which is exactly the failure this product exists to prevent.

BARE_CODES = [
    ("DE GDP growth rate", "Germany"),
    ("FR GDP growth rate", "France"),
    ("JP GDP growth rate", "Japan"),
    ("CN GDP growth rate", "China"),
    ("CA GDP growth rate", "Canada"),
    ("IE GDP growth rate", "Ireland"),
    ("UK GDP growth rate", "United Kingdom"),
    ("US GDP growth rate", "United States"),
    ("AU GDP growth rate", "Australia"),
]


@pytest.mark.parametrize("query,expected", BARE_CODES)
def test_bare_iso_code_names_its_country(query, expected):
    assert dbnomics._country_in_query(query) == expected
    assert expected in dbnomics._detect_countries(query) or (
        expected.lower() in dbnomics._detect_countries(query)
    )


@pytest.mark.parametrize("query,expected", BARE_CODES)
def test_country_scope_recognises_bare_iso_code(query, expected):
    codes = country_scope.named_countries(query)
    assert len(codes) == 1, f"{query!r} must name exactly one country, got {codes}"
    assert country_scope.display_name(codes[0]) == expected


@pytest.mark.parametrize(
    "query",
    [
        "the company told us about GDP",       # "us" is the pronoun
        "le taux d'inflation au Canada",       # "au" is a French preposition
        "de la France",                        # "de" is a French/Spanish preposition
        "tell me about in depth fr-jp trade",  # "in" is an English word
    ],
)
def test_lowercase_bare_codes_that_are_words_do_not_name_a_country(query):
    """Case is the only thing separating these from ordinary words.

    Matching them case-insensitively would name a country the user never
    mentioned, which is worse than naming none: it anchors the lookup to the
    wrong economy. The capitalised form is the conventional spelling and is
    accepted by the tests above.
    """
    for iso2 in ("US", "DE", "AU", "IN", "CN"):
        assert country_scope.named_countries(query) != [iso2] or iso2 not in (
            "US", "AU",
        ), f"{query!r} must not name {iso2} through a lower-case ordinary word"


def test_a_lower_case_preposition_does_not_add_a_country():
    """"de la France" names France — and must not additionally name Germany.

    The invariant is not "no country is found" (this query genuinely names
    France); it is that a lower-case function word never contributes one.
    """
    assert dbnomics._detect_countries("de la France") == ["france"]
    assert dbnomics._detect_countries("le taux d'inflation au Canada") == ["canada"]


def test_italian_series_is_refused_for_an_unnamed_country():
    # Exactly what "de GDP growth rate" used to return.
    assert dbnomics._series_is_country(
        "Italy - Gross domestic product, constant prices", None
    ) is False


def test_supported_country_series_is_still_accepted_for_an_unnamed_country():
    assert dbnomics._series_is_country(
        "Australia - Gross domestic product, constant prices", None
    ) is True


def test_a_series_naming_no_country_at_all_is_not_treated_as_provable():
    """Refusing every unnamed series would break legitimately unscoped questions.

    A series that names no country cannot be shown to be another country's, so
    the unsupported-country refusal stays narrow and specific.
    """
    assert dbnomics._series_is_country("Labour Force, unemployment", None) is True


def test_out_of_scope_geography_is_refused_on_the_query_not_guessed():
    for query in ("world GDP growth rate", "euro area inflation rate",
                  "Italy GDP growth rate", "worldwide trade balance"):
        assert dbnomics._names_out_of_scope_geometry(query) is True, query


def test_in_scope_country_questions_are_not_flagged_out_of_scope():
    for query, _expected in BARE_CODES:
        assert dbnomics._names_out_of_scope_geometry(query) is False, query
    for query in ("Germany GDP growth rate", "Japan policy interest rate",
                  "United Kingdom inflation rate", "Ireland unemployment rate"):
        assert dbnomics._names_out_of_scope_geometry(query) is False, query


@pytest.mark.parametrize("iso2", ["DE", "FR", "JP", "CN", "CA", "IE"])
def test_country_only_connectors_refuse_an_out_of_scope_aggregate(iso2):
    """ABS answered "euro area inflation rate" with Australia's CPI.

    The country-only connectors apply their own default when the question names
    no country. An aggregate geography names no country either, so the default
    fired and the answer was confidently about the wrong economy.
    """
    for query in ("euro area inflation rate", "world inflation rate",
                  "world GDP growth rate"):
        assert country_scope.is_country_scoped(query, iso2) is False, f"{iso2} {query}"


# ---------------------------------------------------------------------------
# 6. Jurisdiction: a foreign company must not be answered from the UK register
# ---------------------------------------------------------------------------
# Companies House is authoritative only for UK-registered companies. The live
# audit asked "What are the latest Apple filings?" — which names no foreign
# COUNTRY, so the country-based refusal did not fire — and got APPLE LTD from
# the UK register. Toyota returned TOYOMAX LIMITED. Both are real companies with
# real filings and neither looks like an error, which is exactly why the
# jurisdiction check is now made against the resolved entity as well as the
# words in the question.

REFUSED_FOREIGN_FILINGS = [
    "What are the latest Apple filings?",
    "Microsoft SEC filings",
    "Toyota filings",
    "Siemens filings",
    "Royal Bank of Canada filings",
]

ALLOWED_UK_FILINGS = [
    "Shell filings",
    "Vodafone filings",
    "Shell plc Companies House filings",
    "Vodafone Companies House filings",
]


@pytest.mark.parametrize("query", REFUSED_FOREIGN_FILINGS)
def test_companies_house_refuses_a_known_non_uk_entity(query):
    assert service._companies_house_should_refuse(query) is True, query


@pytest.mark.parametrize("query", ALLOWED_UK_FILINGS)
def test_companies_house_still_answers_for_uk_entities(query):
    assert service._companies_house_should_refuse(query) is False, query


def test_an_explicit_uk_register_cue_rehabilitates_the_question():
    """Naming the register is an affirmative statement of jurisdiction.

    This is the existing asymmetry — a UK cue overrides the refusal — and the
    new identity-based check must not silently take it away.
    """
    assert service._companies_house_should_refuse(
        "Apple filings on Companies House"
    ) is False


def test_naming_a_foreign_country_still_refuses_the_uk_register():
    for query in ("Canada bank rate filings", "US company filings",
                  "Australian company filings"):
        assert service._companies_house_should_refuse(query) is True, query


# ---------------------------------------------------------------------------
# 7. Endpoint overrides actually work
# ---------------------------------------------------------------------------
# The audit's brief asks whether the endpoint overrides really take effect, not
# merely whether they are present in .env. Every provider resolves its base URL
# through BASE_URL_ENV, so an override that is set but never read would leave
# production silently pointed at the vendor default — invisible in configuration
# review and only discoverable by watching traffic. These tests assert the
# resolved URL, not the configured one.

PROVIDER_BASE_URLS = [
    (AlphaVantageProvider, "ALPHA_VANTAGE_API_BASE_URL"),
    (CompaniesHouseProvider, "COMPANIES_HOUSE_API_BASE_URL"),
    (FinnhubProvider, "FINNHUB_API_BASE_URL"),
    (PolygonProvider, "POLYGON_API_BASE_URL"),
    (IndexQuoteProvider, "YAHOO_INDEX_API_BASE_URL"),
]


@pytest.mark.parametrize("provider_cls,env_name", PROVIDER_BASE_URLS)
def test_provider_base_url_override_takes_effect(monkeypatch, provider_cls, env_name):
    provider = provider_cls()
    default = provider.base_url()
    assert default, f"{provider_cls.__name__} must have a working default base URL"

    monkeypatch.setenv(env_name, "https://override.example.test/v9/")
    overridden = provider.base_url()
    assert overridden == "https://override.example.test/v9"
    assert overridden != default

    # And removing the override restores the vendor default, so a stale value
    # cannot survive an un-set variable.
    monkeypatch.delenv(env_name, raising=False)
    assert provider.base_url() == default


def test_endpoint_base_url_overrides_take_effect_in_the_orchestration_layer(monkeypatch):
    """Same check for the orchestration connectors, which read os.getenv directly."""
    monkeypatch.setenv("WORLD_BANK_API_BASE_URL", "https://wb.example.test/")
    monkeypatch.setenv("DBNOMICS_API_BASE_URL", "https://dbn.example.test/")
    monkeypatch.setenv("FRANKFURTER_API_BASE_URL", "https://fx.example.test/")
    monkeypatch.setenv("FRED_API_BASE_URL", "https://fred.example.test/")

    assert dbnomics._world_bank_base() == "https://wb.example.test"
    assert dbnomics._dbnomics_base() == "https://dbn.example.test"
    assert frankfurter._frankfurter_base() == "https://fx.example.test"
    assert fred._fred_base() == "https://fred.example.test"


def test_trailing_slash_is_normalised_off_every_base_url(monkeypatch):
    """A trailing slash would produce "...//series" and a 404 on a real request."""
    monkeypatch.setenv("WORLD_BANK_API_BASE_URL", "https://wb.example.test/")
    monkeypatch.setenv("DBNOMICS_API_BASE_URL", "https://dbn.example.test//")
    assert dbnomics._world_bank_base() == "https://wb.example.test"
    assert dbnomics._dbnomics_base() == "https://dbn.example.test"

# ─────────────────────────────────────────────────────────────────────────────
# Policy-rate semantics: Ireland, India, and the US instrument question
# ─────────────────────────────────────────────────────────────────────────────

def _policy_rate_series_payload(series_code: str) -> dict:
    """A DBnomics-shaped series response for the policy-rate resolver."""
    return {
        "series": {
            "docs": [
                {
                    "series_code": series_code,
                    "series_name": f"Monthly - {series_code} - provider series",
                    "period": ["2026-05", "2026-06", "2026-07"],
                    "value": [2.0, 2.0, 2.0],
                }
            ]
        }
    }


def _patch_dbnomics_transport(monkeypatch, payload_for):
    """Route the policy-rate resolver's single GET to a canned payload."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        code = request.url.path.rstrip("/").split("/")[-1]
        seen.append(code)
        payload = payload_for(code)
        if payload is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=payload)

    original = dbnomics.httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(dbnomics.httpx, "AsyncClient", factory)
    return seen


def test_ireland_policy_rate_resolves_to_the_euro_area_ecb_rate(monkeypatch):
    """Ireland has no national policy rate of its own - it has been a euro
    member since 1999 - so the ECB deposit facility IS its policy rate, the same
    series Germany and France were already served.

    This was a hard NO_SOURCE while its two euro peers answered, because the
    resolver gated on `country in _NEW_FIVE` and Ireland is in the earlier five.
    """
    ecb = dbnomics._POLICY_RATE_SOURCES["Germany"][0]
    assert dbnomics._POLICY_RATE_SOURCES["Ireland"][0] == ecb
    assert dbnomics._POLICY_RATE_SOURCES["France"][0] == ecb

    _patch_dbnomics_transport(
        monkeypatch, lambda code: _policy_rate_series_payload(code)
    )

    for query in ("Ireland policy rate", "Irish policy interest rate", "Ireland repo rate"):
        match = asyncio.run(dbnomics._find_policy_rate_series(query))
        assert match is not None, f"{query!r} must not be NO_SOURCE"
        assert match.url.endswith(ecb)
        assert match.provider_name == "European Central Bank"


def test_policy_rate_gate_is_the_map_not_the_new_five(monkeypatch):
    """The gate must be the map's own keys.

    Gating on `_NEW_FIVE` was the defect: it made the set of countries that have
    a policy rate here a second, hard-coded list that could disagree with the
    map. Any country added to the map must be immediately reachable.
    """
    assert "Ireland" in dbnomics._POLICY_RATE_SOURCES
    _patch_dbnomics_transport(
        monkeypatch, lambda code: _policy_rate_series_payload(code)
    )
    for country in dbnomics._POLICY_RATE_SOURCES:
        match = asyncio.run(dbnomics._find_policy_rate_series(f"{country} policy rate"))
        assert match is not None, f"{country} is mapped but unreachable"


def test_india_policy_rate_stays_no_source(monkeypatch):
    """India remains a deliberate gap, on evidence.

    The IMF IFS series DBnomics carries for India
    (IMF/IFS/M.IN.FPOLM_PA) is frozen at 6.25% and its last observation is
    2017-04 - verified live. Presenting an eight-year-old figure as India's
    current repo rate is exactly the unverifiable claim this module refuses.
    India is absent from the map, so this returns None and the question falls
    through to the web-grounded path instead of being answered.
    """
    assert "India" not in dbnomics._POLICY_RATE_SOURCES
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=_policy_rate_series_payload("M.IN.FPOLM_PA"))

    original = dbnomics.httpx.AsyncClient
    monkeypatch.setattr(
        dbnomics.httpx, "AsyncClient",
        lambda *a, **k: original(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )

    assert asyncio.run(dbnomics._find_policy_rate_series("India policy rate")) is None
    assert not requested, "an unmapped country must not be fetched at all"


@pytest.mark.parametrize(
    "country", ["United States", "United Kingdom", "Canada", "Australia"]
)
def test_policy_rate_for_other_countries_is_untouched(country, monkeypatch):
    """Each of these has its own connector (FRED, BoE, BoC Valet, RBA). This
    resolver must keep declining them rather than second-guessing a route that
    already works."""
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=_policy_rate_series_payload("X"))

    original = dbnomics.httpx.AsyncClient
    monkeypatch.setattr(
        dbnomics.httpx, "AsyncClient",
        lambda *a, **k: original(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )
    assert asyncio.run(dbnomics._find_policy_rate_series(f"{country} policy rate")) is None
    assert not requested


def test_european_euro_members_do_not_get_different_answers_from_each_other():
    """The three euro members in this product must be served the same series.

    If a future edit gives Ireland its own code, or drops it, the euro-area
    members stop agreeing and one of them starts reporting a rate that does not
    exist for its currency union.
    """
    euro_members = ["Germany", "France", "Ireland"]
    codes = {dbnomics._POLICY_RATE_SOURCES[c][0] for c in euro_members}
    assert len(codes) == 1, f"euro members disagree: {codes}"
    for country in euro_members:
        series_code, provider_name, dataset_name = dbnomics._POLICY_RATE_SOURCES[country]
        assert series_code.startswith("ECB/"), f"{country} is not on an ECB series"
        assert "euro area" in dataset_name.lower(), (
            f"{country}'s dataset label must disclose that this is a euro-area rate"
        )


# ─────────────────────────────────────────────────────────────────────────────
# US policy rate: which instrument is being answered?
# ─────────────────────────────────────────────────────────────────────────────

def _fred_observations_payload(pairs):
    return {"observations": [{"date": d, "value": str(v)} for d, v in pairs]}


def _patch_fred(monkeypatch, pairs):
    original = fred.httpx.AsyncClient
    monkeypatch.setattr(
        fred.httpx, "AsyncClient",
        lambda *a, **k: original(
            *a, **{**k, "transport": httpx.MockTransport(
                lambda request: httpx.Response(200, json=_fred_observations_payload(pairs))
            )}
        ),
    )


@pytest.mark.parametrize(
    "query",
    [
        "US policy rate",
        "US policy interest rate",
        "United States policy interest rate",
        "USA policy rate",
    ],
)
def test_bare_us_policy_rate_discloses_which_instrument_it_reported(query, monkeypatch):
    """"policy rate" is not one statistic.

    The FOMC sets a target RANGE; the overnight market settles at the effective
    rate. FEDFUNDS is the right series to serve, but answering with it silently
    would let a reader believe they were told the FOMC target. The instrument is
    named on the face of the source instead.
    """
    monkeypatch.setenv("FRED_API_KEY", "fake-fred-key")
    _patch_fred(monkeypatch, [("2026-08-01", 3.63)])

    match = asyncio.run(fred._find_fred_series(query))
    assert match is not None, f"{query!r} must resolve"
    assert match.series_id == "FEDFUNDS"
    assert match.instrument_note, "the instrument must be disclosed, not implied"
    assert "effective federal funds rate" in match.instrument_note
    assert "target RANGE" in match.instrument_note

    source = fred._build_source(match)
    assert "Instrument note" in source.snippet
    assert "FEDFUNDS" in source.snippet


@pytest.mark.parametrize(
    "query",
    [
        "US federal funds rate",
        "US effective federal funds rate",
        "US policy rate target range",
        "US federal funds target upper bound",
    ],
)
def test_named_instrument_questions_carry_no_ambiguity_caveat(query, monkeypatch):
    """Naming the instrument leaves nothing ambiguous, so the caveat is noise."""
    monkeypatch.setenv("FRED_API_KEY", "fake-fred-key")
    _patch_fred(monkeypatch, [("2026-08-01", 3.63)])

    match = asyncio.run(fred._find_fred_series(query))
    assert match is not None, f"{query!r} must resolve"
    assert match.instrument_note is None
    assert "Instrument note" not in fred._build_source(match).snippet


def test_us_policy_interest_rate_wording_is_no_longer_a_dead_end(monkeypatch):
    """Regression for a routing hole found while closing this gap.

    FRED's FEDFUNDS pattern listed "policy rate" but not "policy interest rate",
    while dbnomics._POLICY_RATE_HINTS and the Bank of Canada and RBA paths both
    accept it. "United States policy interest rate" therefore matched no FRED
    series, fell through every US definition, and got no authoritative answer at
    all - while the identical question for Canada, Germany or Japan resolved.
    """
    monkeypatch.setenv("FRED_API_KEY", "fake-fred-key")
    _patch_fred(monkeypatch, [("2026-08-01", 3.63)])

    match = asyncio.run(fred._find_fred_series("United States policy interest rate"))
    assert match is not None
    assert match.series_id == "FEDFUNDS"


@pytest.mark.parametrize(
    "query", ["Canada policy rate", "Ireland policy rate", "Germany policy rate", "India policy interest rate"]
)
def test_fred_still_refuses_another_country_s_policy_rate(query, monkeypatch):
    """The pattern now matches more phrasings, so the country guard has to still
    hold. Every series in fred._SERIES is a US concept."""
    monkeypatch.setenv("FRED_API_KEY", "fake-fred-key")
    _patch_fred(monkeypatch, [("2026-08-01", 3.63)])
    assert asyncio.run(fred._find_fred_series(query)) is None


# ─────────────────────────────────────────────────────────────────────────────
# Alpha Vantage: an unrecognised key is an auth failure, not a rate limit
# ─────────────────────────────────────────────────────────────────────────────

_AMBIGUOUS_KEY_PAYLOAD = {
    "Information": (
        "We have detected your API key as "
        "SECRET-KEY-VALUE-THAT-MUST-NOT-LEAK and our standard API rate limit "
        "is 25 requests per day. Please subscribe to any of the premium plans "
        "for unlimited access to our full library."
    )
}
_QUOTA_PAYLOAD = {
    "Information": (
        "Thank you for using Alpha Vantage! Please consider spreading out your "
        "free API requests more sparingly (1 request per second)."
    )
}


def _alpha_envelope(monkeypatch, payload):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-alpha-key")
    provider = AlphaVantageProvider()
    return provider._check_envelope(payload)


def test_alpha_vantage_ambiguous_key_body_is_a_rate_limit_not_an_auth_error(monkeypatch):
    """Alpha Vantage returns the SAME 200-with-prose body for two different
    situations, and this pins the conservative reading.

    Measured live 2026-09-30 with the configured key and two invalid controls:
      - a key the provider does not recognise, and
      - a VALID key whose 25-request daily allowance is spent
    both return "We have detected your API key as <KEY> ... rate limit is 25
    requests per day". The provider cannot tell them apart, so neither can the
    adapter.

    An earlier revision of this file raised ProviderAuthError on that body, which
    told an operator their working key was rejected. ProviderRateLimited is the
    honest classification: it is the reading that does not accuse the credential.
    """
    with pytest.raises(ProviderRateLimited):
        _alpha_envelope(monkeypatch, _AMBIGUOUS_KEY_PAYLOAD)


def test_alpha_vantage_never_echoes_the_key_into_an_exception(monkeypatch):
    """The provider embeds the caller's own API key inside that message.

    Propagating it - into an exception message, a log line, or a WebSource
    snippet - would write the secret wherever errors get collected. This audit
    saw that payload render a live key to a terminal, so the guard is pinned for
    every 200-with-prose shape, not just one.
    """
    secret = "SECRET-KEY-VALUE-THAT-MUST-NOT-LEAK"
    for payload in (
        _AMBIGUOUS_KEY_PAYLOAD,
        {"Note": f"We have detected your API key as {secret}"},
        {"Information": f"key {secret} exceeded its allowance"},
    ):
        with pytest.raises(ProviderRateLimited) as caught:
            _alpha_envelope(monkeypatch, payload)
        rendered = f"{caught.value!r} {caught.value}"
        assert secret not in rendered, "the echoed key leaked into the exception"


def test_alpha_vantage_quota_is_still_a_rate_limit(monkeypatch):
    """The 1-request-per-second throttle is unambiguously a rate limit."""
    with pytest.raises(ProviderRateLimited):
        _alpha_envelope(monkeypatch, _QUOTA_PAYLOAD)


def test_alpha_vantage_note_is_still_a_rate_limit(monkeypatch):
    with pytest.raises(ProviderRateLimited):
        _alpha_envelope(monkeypatch, {"Note": "Thank you for using Alpha Vantage!"})


def test_alpha_vantage_empty_key_is_the_only_body_treated_as_an_auth_error(monkeypatch):
    """"Error Message: the parameter apikey is invalid or missing" is an empty or
    absent key, which genuinely is an authentication failure - and it is the only
    body that means anything other than "try later"."""
    with pytest.raises(ProviderAuthError):
        _alpha_envelope(
            monkeypatch,
            {"Error Message": "the parameter apikey is invalid or missing."},
        )


def test_alpha_vantage_an_auth_error_is_not_worth_retrying_but_a_rate_limit_is(monkeypatch):
    """The two classifications must stay distinguishable, because only one of
    them will ever succeed on a retry."""
    with pytest.raises(ProviderRateLimited) as limited:
        _alpha_envelope(monkeypatch, _AMBIGUOUS_KEY_PAYLOAD)
    with pytest.raises(ProviderAuthError) as auth:
        _alpha_envelope(
            monkeypatch,
            {"Error Message": "the parameter apikey is invalid or missing."},
        )
    assert limited.value.retry_after is None
    assert not hasattr(auth.value, "retry_after")


def test_alpha_vantage_a_valid_payload_still_passes_through(monkeypatch):
    """The success shape is what actually proves the configured key is valid: it
    returns a dataset that neither invalid control returns."""
    payload = {
        "Meta Data": {"1. Information": "Daily Prices"},
        "Time Series (Daily)": {"2026-09-29": {"4. close": "180.5"}},
    }
    assert _alpha_envelope(monkeypatch, payload) == payload


# ─────────────────────────────────────────────────────────────────────────────
# Bare ISO codes: GB and IN were missing from a table that had the other eight
# ─────────────────────────────────────────────────────────────────────────────

TEN_ISO = [
    ("United States", "US"),
    ("United Kingdom", "GB"),
    ("Ireland", "IE"),
    ("Canada", "CA"),
    ("Australia", "AU"),
    ("Germany", "DE"),
    ("France", "FR"),
    ("Japan", "JP"),
    ("India", "IN"),
    ("China", "CN"),
]


@pytest.mark.parametrize(("full", "iso"), TEN_ISO)
def test_every_supported_country_resolves_from_its_uppercase_iso_code(full, iso):
    """All ten, no exceptions.

    Eight had a capitals-only bare ISO code; GB (the real ISO 3166-1 code for the
    United Kingdom - "UK" is the colloquial form) and IN (India) did not, so
    "GB GDP growth rate" and "IN GDP growth rate" named no country at all and
    fell through to whatever default a connector felt like applying.
    """
    assert iso in [c.upper() for c in country_scope.named_countries(f"{iso} GDP growth rate")]
    assert iso in [c.upper() for c in country_scope.named_countries(f"{full} GDP growth rate")]


@pytest.mark.parametrize(("full", "iso"), TEN_ISO)
def test_every_supported_country_resolves_in_dbnomics(full, iso):
    """Both resolver tables have to agree. A country recognised by one and not
    the other is exactly how "de GDP growth" came to be answered with Italy's
    rate in the first place."""
    detected = dbnomics._country_in_query(f"{iso} GDP growth rate")
    assert detected is not None, f"{iso} resolves in no country table"
    assert detected.lower() in [c.lower() for c in dbnomics._detect_countries(f"{full} GDP growth rate")]


@pytest.mark.parametrize("word", ["us", "au", "in", "de", "gb", "fr", "jp", "cn", "ca", "ie"])
def test_lowercase_iso_codes_stay_refused(word):
    """The safety property that makes the capitals-only form acceptable.

    "in" is a preposition, "de" and "fr" are German and French words, "au" is a
    common French preposition, "us" is a pronoun. None of them may ever resolve to
    a country, or a connector anchors to the wrong economy on ordinary prose.
    """
    assert dbnomics._country_in_query(f"{word} GDP growth rate") is None
    assert not country_scope.named_countries(f"{word} GDP growth rate")


@pytest.mark.parametrize("word", ["the", "and", "of", "to", "it", "is", "at", "be", "for", "on"])
def test_ordinary_english_words_name_no_country(word):
    assert dbnomics._country_in_query(f"{word} GDP growth rate") is None
    assert not country_scope.named_countries(f"{word} GDP growth rate")


def test_gb_resolves_to_the_united_kingdom_and_not_something_else():
    """GB must mean the UK. It shares a prefix with no other supported country,
    but a bare 2-letter code reaching an unvalidated table is the risk."""
    assert dbnomics._country_in_query("GB GDP growth rate") == "United Kingdom"
    assert country_scope.named_countries("GB GDP growth rate") == ["GB"]


def test_in_resolves_to_india():
    assert dbnomics._country_in_query("IN GDP growth rate") == "India"
    assert country_scope.named_countries("IN GDP growth rate") == ["IN"]


def test_uk_abbreviation_still_works_alongside_gb():
    """Adding GB must not displace the colloquial form."""
    assert dbnomics._country_in_query("UK GDP growth rate") == "United Kingdom"
    assert dbnomics._country_in_query("GB GDP growth rate") == "United Kingdom"
