"""Market-data subsystem tests.

Every provider call is served by an httpx MockTransport, so nothing here needs
an API key or reaches a live service — a test that silently skips when a key is
absent is a test that never runs in CI.

Keys are set to dummy values via monkeypatch where an adapter needs to look
configured; they are never real and never leave the process.
"""
import os
import sys

# Ensure backend root is in search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
import pytest

from app.domains.market_data import registry
from app.domains.market_data.http import as_float, request_json
from app.domains.market_data.identity import find_company_number, find_ticker, resolve_local
from app.domains.market_data.providers.alpha_vantage import AlphaVantageProvider
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.providers.finnhub import FinnhubProvider
from app.domains.market_data.providers.polygon import PolygonProvider
from app.domains.market_data.schemas import (
    EntityRef,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderUnavailable,
)


def client_returning(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_client(payload, status: int = 200, headers: dict | None = None) -> httpx.AsyncClient:
    return client_returning(lambda request: httpx.Response(status, json=payload, headers=headers or {}))


# ── identity ─────────────────────────────────────────────────────────────────

def test_finds_uk_company_number():
    assert find_company_number("Show me filings for 01026167") == "01026167"
    assert find_company_number("Scottish company SC123456 filings") == "SC123456"
    assert find_company_number("no number here") == ""
    print("test_finds_uk_company_number: PASSED")


def test_uppercase_jargon_is_not_a_ticker():
    """The false-positive class that matters: without a stopword guard, generic
    accounting questions resolve to real listed companies."""
    for query in ("How does US GAAP treat R&D?", "What is the VAT rate?", "Explain EPS and ROE"):
        assert find_ticker(query) == "", query
    print("test_uppercase_jargon_is_not_a_ticker: PASSED")


def test_finds_explicit_ticker_and_known_name():
    assert find_ticker("MSFT share price") == "MSFT"
    assert find_ticker("BARC.L quote") == "BARC.L"
    assert resolve_local("What is Apple's share price?").ticker == "AAPL"
    print("test_finds_explicit_ticker_and_known_name: PASSED")


# ── intent detection ─────────────────────────────────────────────────────────

def test_educational_questions_do_not_trigger_market_lookup():
    """"How is revenue recognised under IFRS 15" contains "revenue" but is not
    a request for a company's revenue — firing here would attach a stranger's
    figures to an accounting question."""
    for query in (
        "How is revenue recognised under IFRS 15?",
        "What is EBITDA and how is it calculated?",
        "Explain the difference between gross profit and net profit",
    ):
        assert registry.detect_intent(query) is None, query
    print("test_educational_questions_do_not_trigger_market_lookup: PASSED")


def test_market_intents_are_detected():
    cases = {
        "What is Apple's share price?": registry.INTENT_QUOTE,
        "Show me Barclays filings": registry.INTENT_FILINGS,
        "AAPL price history over the last 30 days": registry.INTENT_HISTORY,
        "What is Tesla's market cap?": registry.INTENT_FUNDAMENTALS,
    }
    for query, expected in cases.items():
        assert registry.detect_intent(query) == expected, query
    print("test_market_intents_are_detected: PASSED")


def test_non_market_question_has_no_intent():
    assert registry.detect_intent("hello") is None
    assert registry.detect_intent("Explain the bank reconciliation process") is None
    print("test_non_market_question_has_no_intent: PASSED")


# ── provider selection / fallback ────────────────────────────────────────────

def test_unconfigured_providers_are_skipped(monkeypatch):
    for var in ("FINNHUB_API_KEY", "POLYGON_API_KEY", "ALPHA_VANTAGE_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert registry.providers_for(registry.INTENT_QUOTE) == []

    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    names = [p.name for p in registry.providers_for(registry.INTENT_QUOTE)]
    assert names == ["finnhub"]
    print("test_unconfigured_providers_are_skipped: PASSED")


def test_filings_route_only_to_companies_house(monkeypatch):
    """No other provider may be consulted as a "fallback" for the UK statutory
    register — none of them hold it."""
    for var in ("FINNHUB_API_KEY", "POLYGON_API_KEY", "ALPHA_VANTAGE_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        monkeypatch.setenv(var, "dummy")
    names = [p.name for p in registry.providers_for(registry.INTENT_FILINGS)]
    assert names == ["companies_house"]
    print("test_filings_route_only_to_companies_house: PASSED")


def test_priority_is_configurable(monkeypatch):
    for var in ("FINNHUB_API_KEY", "POLYGON_API_KEY"):
        monkeypatch.setenv(var, "dummy")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_DATA_PRIORITY_STOCK_QUOTE", "polygon,finnhub")
    assert [p.name for p in registry.providers_for(registry.INTENT_QUOTE)] == ["polygon", "finnhub"]
    print("test_priority_is_configurable: PASSED")


# ── HTTP client behaviour ────────────────────────────────────────────────────

async def test_auth_failure_is_not_retried():
    """A rejected key stays rejected; retrying it risks locking the account."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={})

    async with client_returning(handler) as client:
        with pytest.raises(ProviderAuthError):
            await request_json(client, "test", "https://example.test/x", retries=3)
    assert calls["n"] == 1
    print("test_auth_failure_is_not_retried: PASSED")


async def test_server_error_is_retried_then_raises():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, json={})

    async with client_returning(handler) as client:
        with pytest.raises(ProviderUnavailable):
            await request_json(client, "test", "https://example.test/x", retries=1)
    assert calls["n"] == 2
    print("test_server_error_is_retried_then_raises: PASSED")


async def test_rate_limit_raises_typed_error():
    async with json_client({}, status=429, headers={"Retry-After": "1"}) as client:
        with pytest.raises(ProviderRateLimited):
            await request_json(client, "test", "https://example.test/x", retries=0)
    print("test_rate_limit_raises_typed_error: PASSED")


async def test_non_json_body_is_a_bad_response():
    async with client_returning(lambda r: httpx.Response(200, text="<html>nope</html>")) as client:
        with pytest.raises(ProviderBadResponse):
            await request_json(client, "test", "https://example.test/x", retries=0)
    print("test_non_json_body_is_a_bad_response: PASSED")


def test_as_float_rejects_non_numbers():
    assert as_float("12.5") == 12.5
    for junk in (None, "", "None", "-", "n/a", True, float("nan"), float("inf")):
        assert as_float(junk) is None, junk
    print("test_as_float_rejects_non_numbers: PASSED")


# ── Companies House ──────────────────────────────────────────────────────────

async def test_companies_house_filings(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "dummy")

    def handler(request):
        if "/search/companies" in request.url.path:
            return httpx.Response(200, json={"items": [{"title": "BARCLAYS PLC", "company_number": "00048839"}]})
        if request.url.path.endswith("/filing-history"):
            return httpx.Response(200, json={"items": [
                {"type": "AA", "date": "2026-04-01", "description": "accounts-with-accounts-type-full",
                 "transaction_id": "TX1"},
            ]})
        return httpx.Response(200, json={"company_name": "BARCLAYS PLC", "company_status": "active"})

    async with client_returning(handler) as client:
        filings = await CompaniesHouseProvider().get_filings(client, EntityRef(name="Barclays"))

    assert len(filings) == 1
    assert filings[0].company_number == "00048839"
    assert filings[0].filing_date == "2026-04-01"
    assert filings[0].provider == "companies_house"
    assert "TX1" in filings[0].source_url
    print("test_companies_house_filings: PASSED")


async def test_companies_house_unknown_company_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "dummy")
    async with json_client({"items": []}) as client:
        with pytest.raises(ProviderBadResponse):
            await CompaniesHouseProvider().get_filings(client, EntityRef(name="Nonexistent Ltd"))
    print("test_companies_house_unknown_company_is_reported_not_swallowed: PASSED")


# ── Finnhub ──────────────────────────────────────────────────────────────────

async def test_finnhub_quote(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    monkeypatch.delenv("FINNHUB_REALTIME", raising=False)
    payload = {"c": 214.29, "d": 1.5, "dp": 0.7, "h": 215.0, "l": 212.0, "o": 213.0, "pc": 212.79, "t": 1754899200}
    async with json_client(payload) as client:
        quote = await FinnhubProvider().get_quote(client, EntityRef(ticker="AAPL"))

    assert quote.price == 214.29
    assert quote.provider == "finnhub"
    # Entitlement is operator-declared and defaults to the conservative label.
    assert quote.freshness == "delayed"
    print("test_finnhub_quote: PASSED")


async def test_finnhub_zero_price_means_unknown_symbol(monkeypatch):
    """Finnhub answers 200 with every field zeroed for an unknown symbol. A
    zero must never be reported as a price."""
    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    async with json_client({"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}) as client:
        with pytest.raises(ProviderBadResponse):
            await FinnhubProvider().get_quote(client, EntityRef(ticker="NOPE"))
    print("test_finnhub_zero_price_means_unknown_symbol: PASSED")


async def test_finnhub_realtime_only_when_declared(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    monkeypatch.setenv("FINNHUB_REALTIME", "true")
    async with json_client({"c": 10.0, "t": 1754899200}) as client:
        quote = await FinnhubProvider().get_quote(client, EntityRef(ticker="AAPL"))
    assert quote.freshness == "realtime"
    print("test_finnhub_realtime_only_when_declared: PASSED")


# ── Polygon ──────────────────────────────────────────────────────────────────

async def test_polygon_quote_is_labelled_historical_by_default(monkeypatch):
    """The free tier reaches previous-close only; presenting that as a live
    price would be the exact misrepresentation this labelling prevents."""
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.delenv("POLYGON_REALTIME", raising=False)
    payload = {"results": [{"c": 212.5, "o": 210.0, "h": 213.0, "l": 209.5, "v": 4_000_000, "t": 1754899200000}]}
    async with json_client(payload) as client:
        quote = await PolygonProvider().get_quote(client, EntityRef(ticker="AAPL"))

    assert quote.price == 212.5
    assert quote.freshness == "historical"
    assert quote.market_status == "previous close"
    print("test_polygon_quote_is_labelled_historical_by_default: PASSED")


async def test_polygon_history(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    rows = [{"c": 100 + i, "o": 99 + i, "h": 101 + i, "l": 98 + i, "v": 1000, "t": 1754899200000 + i * 86400000}
            for i in range(5)]
    async with json_client({"results": rows}) as client:
        bars = await PolygonProvider().get_history(client, EntityRef(ticker="AAPL"), limit=5)

    assert len(bars) == 5
    assert bars[-1].close == 104
    assert bars[0].provider == "polygon"
    print("test_polygon_history: PASSED")


async def test_polygon_empty_results_is_a_bad_response(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    async with json_client({"results": []}) as client:
        with pytest.raises(ProviderBadResponse):
            await PolygonProvider().get_quote(client, EntityRef(ticker="NOPE"))
    print("test_polygon_empty_results_is_a_bad_response: PASSED")


# ── Alpha Vantage ────────────────────────────────────────────────────────────

async def test_alpha_vantage_throttle_arrives_as_http_200(monkeypatch):
    """The provider signals throttling in a 200 body. Read naively that looks
    like "no data" and the answer becomes a confident "not available"."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "dummy")
    async with json_client({"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is..."}) as client:
        with pytest.raises(ProviderRateLimited):
            await AlphaVantageProvider().get_quote(client, EntityRef(ticker="AAPL"))
    print("test_alpha_vantage_throttle_arrives_as_http_200: PASSED")


async def test_alpha_vantage_information_key_is_also_a_throttle(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "dummy")
    async with json_client({"Information": "the standard API rate limit is 25 requests per day"}) as client:
        with pytest.raises(ProviderRateLimited):
            await AlphaVantageProvider().get_quote(client, EntityRef(ticker="AAPL"))
    print("test_alpha_vantage_information_key_is_also_a_throttle: PASSED")


async def test_alpha_vantage_quote(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "dummy")
    payload = {"Global Quote": {
        "01. symbol": "AAPL", "02. open": "213.00", "03. high": "215.00", "04. low": "212.00",
        "05. price": "214.29", "06. volume": "40000000", "07. latest trading day": "2026-08-11",
        "08. previous close": "212.79", "09. change": "1.50", "10. change percent": "0.7050%",
    }}
    async with json_client(payload) as client:
        quote = await AlphaVantageProvider().get_quote(client, EntityRef(ticker="AAPL"))

    assert quote.price == 214.29
    assert quote.change_percent == 0.7050
    assert quote.freshness == "delayed"
    print("test_alpha_vantage_quote: PASSED")


async def test_alpha_vantage_error_message_is_a_bad_response(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "dummy")
    async with json_client({"Error Message": "Invalid API call"}) as client:
        with pytest.raises(ProviderBadResponse):
            await AlphaVantageProvider().get_quote(client, EntityRef(ticker="???"))
    print("test_alpha_vantage_error_message_is_a_bad_response: PASSED")


# ── entity resolution → provider seam ────────────────────────────────────────
# The bug these cover: a well-known company name resolved locally to a TICKER,
# which made "did we resolve an identifier?" true, so the Companies House
# search never ran and the provider was handed an empty name. Both adapter
# tests and intent tests passed while "Show me Barclays filings" returned
# nothing — the defect lived purely in the seam between them.

async def test_filings_resolution_reaches_a_company_number(monkeypatch):
    """A ticker is not a usable identifier for Companies House; the resolver
    must go and find the company number."""
    from app.domains.market_data.service import _resolve_entity

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "dummy")

    def handler(request):
        assert request.url.params.get("q"), "Companies House was searched with an empty query"
        return httpx.Response(200, json={"items": [{"title": "BARCLAYS PLC", "company_number": "00048839"}]})

    async with client_returning(handler) as client:
        ref = await _resolve_entity(
            client, "Show me Barclays filings", [CompaniesHouseProvider()], registry.INTENT_FILINGS
        )

    assert ref.company_number == "00048839"
    print("test_filings_resolution_reaches_a_company_number: PASSED")


async def test_quote_resolution_is_satisfied_by_a_ticker(monkeypatch):
    """The converse: a market intent needs a ticker, and a locally-resolved one
    is enough — no search round-trip should happen."""
    from app.domains.market_data.service import _resolve_entity

    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")

    def handler(request):
        raise AssertionError("no provider search should be needed when a ticker is already known")

    async with client_returning(handler) as client:
        ref = await _resolve_entity(
            client, "What is Apple's share price?", [FinnhubProvider()], registry.INTENT_QUOTE
        )

    assert ref.ticker == "AAPL"
    print("test_quote_resolution_is_satisfied_by_a_ticker: PASSED")


async def test_company_lookup_by_name_resolves_a_number(monkeypatch):
    """"Find UK company Rolls-Royce" — the other query this bug silenced."""
    from app.domains.market_data.service import _resolve_entity

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "dummy")
    async with json_client({"items": [{"title": "ROLLS-ROYCE PLC", "company_number": "01003142"}]}) as client:
        ref = await _resolve_entity(
            client, "Find UK company Rolls-Royce", [CompaniesHouseProvider()], registry.INTENT_LOOKUP
        )
    assert ref.company_number == "01003142"
    print("test_company_lookup_by_name_resolves_a_number: PASSED")


def test_search_hint_is_not_used_as_a_display_name():
    """The hint is a search term. Displayed as a name it produced "Apple s" —
    a possessive stripped after its apostrophe. Only confirmed names surface."""
    from app.domains.market_data.identity import company_name_hint

    assert company_name_hint("What is Apple's share price?") == "Apple"
    assert company_name_hint("Show me Rolls-Royce filings") == "Rolls-Royce"
    # A confirmed name from the well-known table IS safe to display.
    assert resolve_local("What is Apple's share price?").name == "Apple"
    print("test_search_hint_is_not_used_as_a_display_name: PASSED")


def test_requested_bars_honours_an_explicit_span():
    """"the last 30 days" must not silently become ten data points."""
    assert registry.requested_bars("AAPL price history over the last 30 days") == 30
    assert registry.requested_bars("AAPL over the past 3 months") == 63
    assert registry.requested_bars("AAPL price history") == 30
    assert registry.requested_bars("AAPL over the last 999 years") == 400  # capped
    print("test_requested_bars_honours_an_explicit_span: PASSED")


# ── connector boundary ───────────────────────────────────────────────────────

async def test_connector_returns_nothing_without_any_provider(monkeypatch):
    """Fail-soft: with no keys configured the connector is silent, and the
    answer falls back to the normal web-grounded path."""
    from app.orchestration.market_data import fetch_market_sources

    for var in ("FINNHUB_API_KEY", "POLYGON_API_KEY", "ALPHA_VANTAGE_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert await fetch_market_sources("What is Apple's share price?") == []
    print("test_connector_returns_nothing_without_any_provider: PASSED")


async def test_connector_ignores_non_market_questions(monkeypatch):
    from app.orchestration.market_data import fetch_market_sources

    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    assert await fetch_market_sources("How is revenue recognised under IFRS 15?") == []
    print("test_connector_ignores_non_market_questions: PASSED")


def test_large_figures_are_readable_not_scientific_notation():
    """A 1.3-trillion market cap rendered as "1.307e+06" is technically correct
    and gets misread by orders of magnitude. Scale words, not exponents."""
    from app.orchestration.market_data import _metric_value
    from app.domains.market_data.schemas import FinancialMetric

    def metric(value, unit):
        return FinancialMetric(metric="x", value=value, provider="p", unit=unit)

    rendered = _metric_value(metric(1_307_000_000_000, "USD"))
    assert "e+" not in rendered
    assert "1.31 trillion" in rendered

    assert _metric_value(metric(18.85, "%")) == "18.85%"
    assert _metric_value(metric(1.077, "per share")) == "1.08 per share"
    assert _metric_value(metric(0.1076, "ratio")) == "0.1076"
    print("test_large_figures_are_readable_not_scientific_notation: PASSED")


async def test_market_cap_is_scaled_to_absolute_units(monkeypatch):
    """Finnhub reports market cap in millions. get_company_profile scaled it
    and get_fundamentals did not — the same provider disagreeing with itself by
    a factor of a million."""
    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    async with json_client({"metric": {"marketCapitalization": 1_307_000}}) as client:
        metrics = await FinnhubProvider().get_fundamentals(client, EntityRef(ticker="TSLA"))
    cap = next(m for m in metrics if m.metric.startswith("Market cap"))
    assert cap.value == 1_307_000_000_000
    assert cap.unit == "USD"
    print("test_market_cap_is_scaled_to_absolute_units: PASSED")


def test_websource_carries_freshness_for_citations():
    """The provenance fields must survive into WebSource — they are what the
    citation renders, and a delayed quote shown as realtime is the failure
    mode this whole labelling chain exists to prevent."""
    from app.orchestration.market_data import _quote_source
    from app.domains.market_data.schemas import StockQuote

    quote = StockQuote(
        symbol="AAPL", price=214.29, provider="finnhub", freshness="delayed",
        fetched_at="2026-08-11T10:00:00+00:00", company_name="Apple Inc.",
    )
    source = _quote_source(quote)
    assert source.provider == "finnhub"
    assert source.freshness == "delayed"
    assert "not real-time" in source.snippet
    print("test_websource_carries_freshness_for_citations: PASSED")
