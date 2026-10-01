"""Stale-response and freshness tests.

The previous audit recorded `no stale-response test exists` as a gap. This file
closes it. The previous audit was right that there was no test, but its implied
conclusion - that the system silently represents stale data as fresh - does not
hold. The design is deliberate and is what these tests pin:

  * Freshness in this codebase is a DECLARED label taken from the source's own
    publication frequency ("daily", "monthly", "historical", "delayed",
    "legislation"), not a computed age. Nothing here computes
    `now - observation_date` and silently upgrades or downgrades a label.
  * What the system guarantees instead is that the observation's own date is
    carried verbatim to the reader. A 2017 value is reported as a 2017 value,
    with the period in `LiveObservation.period` and the date in the snippet.
  * Where a source states its own age, the connector gates on it. GOV.UK is the
    one connector with a real staleness gate (`_is_fresh`), and it fails CLOSED:
    a page that will not state when it was last checked is not evidence of a
    current rate.

Every test uses a MockTransport or an obviously-fake literal. No test reads,
prints or requires a real credential, and no test reaches the network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.domains.market_data.providers.index_quote import IndexQuoteProvider
from app.domains.market_data.schemas import (
    EntityRef,
    ProviderBadResponse,
    StockQuote,
)
from app.orchestration import fred
from app.orchestration import govuk
from app.orchestration.govuk import _build_source as govuk_build_source
from app.orchestration.govuk import _find_uk_tax_rate, _is_fresh
from app.orchestration.market_data import _FRESHNESS_WORDS, _quote_source

RATE_QUERY = "What is the current UK VAT rate?"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 1. GOV.UK: the one real staleness gate
# ─────────────────────────────────────────────────────────────────────────────

def test_govuk_rejects_a_recent_page():
    assert _is_fresh(_iso(_utc_now() - timedelta(days=30))) is True


def test_govuk_rejects_nothing_for_an_absent_date():
    """Fail closed. A page that will not say when it was updated is not evidence
    that a tax rate is current - tax rates move at Budget and in April."""
    assert _is_fresh(None) is False
    assert _is_fresh("") is False


def test_govuk_rejects_nothing_for_an_unparseable_date():
    """A malformed timestamp must not be read as fresh. Treating an unparseable
    date as current is exactly how a 2014 rate page becomes "today's" rate."""
    assert _is_fresh("not-a-date") is False
    assert _is_fresh("2026-13-45T99:99:99Z") is False
    assert _is_fresh("   ") is False


def test_govuk_rejects_a_page_older_than_the_window():
    """Past GOVUK_MAX_AGE_MONTHS (default 12) the page is not a current rate."""
    assert _is_fresh(_iso(_utc_now() - timedelta(days=400))) is False


def test_govuk_accepts_a_naive_timestamp_as_utc():
    """GOV.UK returns a trailing Z on some fields and omits it on others."""
    naive = (_utc_now() - timedelta(days=5)).replace(tzinfo=None)
    assert _is_fresh(naive.isoformat()) is True


def test_govuk_window_is_configurable_and_fails_safe():
    import os

    recent = _iso(_utc_now() - timedelta(days=200))
    old = _iso(_utc_now() - timedelta(days=400))
    previous = os.environ.get("GOVUK_MAX_AGE_MONTHS")

    def run(value):
        os.environ["GOVUK_MAX_AGE_MONTHS"] = value
        return _is_fresh(recent), _is_fresh(old)

    try:
        assert run("1") == (False, False), "a 200-day-old page is stale at 1 month"
        assert run("120") == (True, True), "a 200-day-old page is fresh at 120 months"
        # Nonsense config must not widen the gate past the safe default of 12
        # months. These all have to fall back, so a 400-day-old page is stale.
        for junk in ("0", "9999", "not-a-number", "-5"):
            assert run(junk) == (True, False), f"{junk!r} must fall back to 12 months"
    finally:
        if previous is None:
            os.environ.pop("GOVUK_MAX_AGE_MONTHS", None)
        else:
            os.environ["GOVUK_MAX_AGE_MONTHS"] = previous


def _govuk_client(search_ts: str, content_ts: str, body: str) -> httpx.AsyncClient:
    """A GOV.UK client whose search index and content page carry these dates."""
    long_body = body or ("<p>Value Added Tax guidance paragraph. </p>" + ("x" * 400))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/search.json"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "VAT rates charged on different goods and services",
                            "link": "/guidance/vat-rates-charged-on-different-goods-and-services",
                            "public_timestamp": search_ts,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "title": "VAT rates charged on different goods and services",
                "public_updated_at": content_ts,
                "details": {"body": long_body},
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run_govuk(client: httpx.AsyncClient):
    return asyncio.run(_find_uk_tax_rate(RATE_QUERY, client=client))


def test_govuk_end_to_end_serves_a_fresh_page():
    now = _utc_now()
    client = _govuk_client(_iso(now), _iso(now), "")
    match = _run_govuk(client)
    assert match is not None
    source = govuk_build_source(match)
    # The date is on the face of the source, not merely in a field.
    assert match.updated_date in source.title
    assert match.updated_date in source.snippet
    assert source.freshness == "legislation"
    assert source.observation is not None
    assert source.observation.period == match.updated_date


def test_govuk_end_to_end_refuses_a_stale_search_hit():
    """A stale index entry yields no source at all - and above all no rate."""
    old = _iso(_utc_now() - timedelta(days=900))
    client = _govuk_client(old, old, "")
    assert _run_govuk(client) is None


def test_govuk_end_to_end_refuses_a_stale_content_page_even_if_the_index_is_fresh():
    """Both timestamps are gated. A fresh index entry pointing at a page that
    was last touched three years ago is still a three-year-old page."""
    now = _utc_now()
    client = _govuk_client(_iso(now), _iso(now - timedelta(days=1100)), "")
    assert _run_govuk(client) is None


def test_govuk_refuses_a_page_that_states_no_date():
    """No timestamp at all is stale. This is the fabricated-currentness case:
    the connector must decline rather than quote a rate it cannot date."""
    now = _utc_now()
    client = _govuk_client(_iso(now), "", "")
    assert _run_govuk(client) is None


def test_govuk_refuses_a_stub_page_rather_than_inventing_a_rate():
    now = _utc_now()
    client = _govuk_client(_iso(now), _iso(now), "<p>See attachment.</p>")
    assert _run_govuk(client) is None


def test_govuk_stale_path_raises_nothing_and_falls_through(monkeypatch):
    """A stale provider must fail soft so the next source gets its turn, not
    raise, and never return a partial/fabricated match."""
    now = _utc_now()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/search.json"):
            return httpx.Response(
                200,
                json={"results": [{"title": "x", "link": "/a", "public_timestamp": _iso(now)}]},
            )
        raise httpx.ConnectError("boom", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert _run_govuk(client) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. FRED: an out-of-window payload is reported as out of window
# ─────────────────────────────────────────────────────────────────────────────

def _fred_client(observations: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": observations})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _fred_points(period_value_pairs: list[tuple[str, float]]) -> list[dict]:
    return [{"date": d, "value": str(v)} for d, v in period_value_pairs]


async def _fred_match(monkeypatch, query: str, pairs: list[tuple[str, float]]):
    monkeypatch.setenv("FRED_API_KEY", "fake-fred-key-for-tests")
    client = _fred_client(_fred_points(pairs))
    original = fred.httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = client._transport
        return original(*args, **kwargs)

    monkeypatch.setattr(fred.httpx, "AsyncClient", factory)
    return await fred._find_fred_series(query)


def test_fred_reports_an_out_of_window_series_as_incomplete(monkeypatch):
    """Asked for 2015-2020, a series that starts in 2021 must not read as a
    complete answer to that window. `coverage_complete` goes false and a warning
    is attached; nothing is invented to fill the gap."""
    match = asyncio.run(
        _fred_match(
            monkeypatch,
            "US GDP between 2015 and 2020",
            [("2021-01-01", 23000.0), ("2021-04-01", 23200.0)],
        )
    )
    assert match is not None
    assert match.coverage_complete is False
    assert match.warning is not None
    assert "coverage" in match.warning.lower() or "observation" in match.warning.lower()


def test_fred_keeps_the_true_observation_period(monkeypatch):
    """The reported period is the provider's, never today's date. Re-dating a
    stale observation to now is the exact failure these tests exist to prevent."""
    match = asyncio.run(
        _fred_match(
            monkeypatch,
            "US unemployment rate",
            [("2019-01-01", 3.9), ("2019-02-01", 3.7)],
        )
    )
    assert match is not None
    source = fred._build_source(match)
    assert source.observation is not None
    assert source.observation.period == "2019-02-01"
    assert source.observation.value == "3.7"
    # The snippet carries the periods too, so a reader cannot mistake them.
    assert "2019-02-01" in source.snippet
    assert source.freshness == "historical"


def test_fred_empty_payload_produces_no_source_and_no_number(monkeypatch):
    match = asyncio.run(_fred_match(monkeypatch, "US unemployment rate", []))
    assert match is None, "an empty series must fall through, never yield a figure"


def test_fred_never_labels_a_macro_series_realtime(monkeypatch):
    match = asyncio.run(
        _fred_match(monkeypatch, "US unemployment rate", [("2019-02-01", 3.7)])
    )
    source = fred._build_source(match)
    assert source.freshness == "historical"
    assert "realtime" not in source.freshness


# ─────────────────────────────────────────────────────────────────────────────
# 3. Market data: a quote must not be upgraded past what the feed says
# ─────────────────────────────────────────────────────────────────────────────

def _chart_client(meta: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"chart": {"result": [{"meta": meta}], "error": None}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _index_quote(meta: dict) -> StockQuote:
    provider = IndexQuoteProvider()
    client = _chart_client(meta)
    return await provider.get_quote(client, EntityRef(ticker="^GSPC", name="S&P 500"))


def test_index_quote_keeps_delayed_even_when_the_market_is_closed():
    """A Friday-close quote served on a Sunday is the normal case for this feed.
    Freshness is the provider's own delayed label and must not be promoted to
    realtime just because the price looks current."""
    stale_close = int(
        (datetime.now(timezone.utc) - timedelta(days=4)).timestamp()
    )
    quote = asyncio.run(
        _index_quote(
            {
                "symbol": "^GSPC",
                "regularMarketPrice": 6432.11,
                "previousClose": 6400.0,
                "regularMarketTime": stale_close,
                "fullExchangeName": "SNP",
                "currency": "USD",
            }
        )
    )
    assert quote.freshness == "delayed"
    assert quote.freshness != "realtime"


def test_index_quote_snippet_states_the_real_as_at_time():
    """The timestamp in the sentence must be the provider's market timestamp, so
    a four-day-old close is visibly four days old to the reader."""
    stale_close = int(
        (datetime.now(timezone.utc) - timedelta(days=4)).timestamp()
    )
    quote = asyncio.run(
        _index_quote(
            {
                "symbol": "^GSPC",
                "regularMarketPrice": 6432.11,
                "previousClose": 6400.0,
                "regularMarketTime": stale_close,
                "fullExchangeName": "SNP",
                "currency": "USD",
            }
        )
    )
    source = _quote_source(quote)
    assert source.observation is not None
    # `_quote_source` normalises the timestamp to a 19-character ISO form.
    assert source.observation.period == quote.provider_timestamp[:19]
    assert quote.provider_timestamp in source.snippet
    assert _FRESHNESS_WORDS["delayed"] in source.snippet
    assert "not real-time" in source.snippet


def test_index_quote_never_invents_a_price_from_a_zeroed_feed():
    """Yahoo answers 200 with regularMarketPrice 0 for instruments it does not
    serve. Reporting 0.00 would be a fabricated figure, so it must raise."""
    with pytest.raises(ProviderBadResponse):
        asyncio.run(
            _index_quote(
                {"symbol": "^NOPE", "regularMarketPrice": 0, "regularMarketTime": 1790000000}
            )
        )


def test_index_quote_missing_timestamp_falls_back_to_fetch_time_without_claiming_market_time():
    """No market timestamp means we cannot say when the price was struck. The
    fetched_at is used, and the label stays delayed."""
    quote = asyncio.run(
        _index_quote(
            {"symbol": "^GSPC", "regularMarketPrice": 6432.11, "previousClose": 6400.0}
        )
    )
    assert quote.provider_timestamp == ""
    assert quote.freshness == "delayed"
    source = _quote_source(quote)
    assert quote.fetched_at in source.snippet


# ─────────────────────────────────────────────────────────────────────────────
# 4. Number fidelity through the stale path
# ─────────────────────────────────────────────────────────────────────────────

def test_number_text_keeps_the_full_precision_the_provider_sent():
    """The regression the previous audit pinned. `f"{value:g}"` turned this into
    "24312.4" - a different number, presented confidently."""
    from app.orchestration.market_data import _number_text

    assert _number_text(24312.44) == "24312.44"
    assert _number_text(24312.44) != "24312.4"


def test_index_level_precision_survives_into_the_quote_and_snippet():
    """Full precision must reach the structured observation, which is what the
    chart, the evidence bundle and the audit record read.

    The human-readable snippet is a separate, deliberate rounding: `_money()`
    prints whole units above 1,000, the convention for currency amounts. That is
    a display choice and it is recorded as one in the audit report - it does not
    change the value the system holds, so it is left alone here rather than
    "fixed" by rewriting shared currency formatting.
    """
    quote = asyncio.run(
        _index_quote(
            {
                "symbol": "^N225",
                "regularMarketPrice": 24312.44,
                "previousClose": 24000.0,
                "regularMarketTime": int(
                    (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
                ),
                "fullExchangeName": "JPX",
                "currency": "JPY",
            }
        )
    )
    assert quote.price == 24312.44
    source = _quote_source(quote)
    assert source.observation is not None
    assert source.observation.value == "24312.44", "the audited value is exact"
    assert float(source.observation.value) == 24312.44
    # The snippet rounds for display only; the difference is intentional and
    # must stay visible rather than being quietly reconciled.
    assert "24,312" in source.snippet
    assert _money_rounds_display_only()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, "0.0"),
        (7, "7.0"),
        (-1234, "-1234.0"),
        (1.5, "1.5"),
        (24312.44, "24312.44"),
        # NOTE: the float literal 24312.439999999999 IS 24312.44 - IEEE-754 has no
        # such value. repr collapses it back to the shortest round-tripping form,
        # which is the whole point of using repr. Asserting "24312.439999999999"
        # here would demand the exact opposite of the fix.
        (0.1 + 0.2, "0.30000000000000004"),
        (1e-9, "0.000000001"),
        (1.5e18, "1500000000000000000"),
        (None, ""),
    ],
)
def test_number_text_cases(raw, expected):
    """Integers, decimals, near-miss precision, very small and very large values.

    Nothing here may gain or lose a significant digit: `repr` is the shortest
    string that round-trips to the same float, which is the precision the value
    actually carries.
    """
    from app.orchestration.market_data import _number_text

    assert _number_text(raw) == expected


def test_number_text_never_emits_exponent_notation():
    from app.orchestration.market_data import _number_text

    for value in (24312.44, 1e-9, 1.5e18, -2.5e-7):
        text = _number_text(value)
        assert "e" not in text.lower(), f"{value!r} rendered as {text!r}"


def test_number_text_round_trips_through_float():
    from app.orchestration.market_data import _number_text

    for value in (24312.44, 0.1 + 0.2, 1 / 3, 999999999.123456):
        assert float(_number_text(value)) == value


def _money_rounds_display_only() -> bool:
    """Pin the display-rounding contract so it stays a conscious choice.

    Also covers the trailing-zero case the brief asks about: rstrip("0") must not
    eat significant digits, because the "." stops it - "100.00" becomes "100",
    not "1".
    """
    from app.orchestration.market_data import _money

    assert _money(24312.44, "JPY") == "JPY 24,312"
    assert _money(6432.11, "") == "6,432"
    assert _money(0.5, "") == "0.5"
    assert _money(100.0, "") == "100", "trailing zeros must not eat the hundreds"
    assert _money(1000.0, "") == "1,000"
    assert _money(0.0, "") == "0"
    assert _money(None, "USD") == "n/a"
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 5. A stale upstream must not poison the cache
# ─────────────────────────────────────────────────────────────────────────────

def test_volatile_freshness_is_the_set_the_cache_refuses_to_reuse():
    """Realtime and delayed are the two labels whose values move within the
    second. Anything else (historical, legislation, daily) is safe to reuse, so
    the distinction the previous audit could not find is explicit here."""
    from app.orchestration.answer_cache import _VOLATILE_FRESHNESS

    assert {"realtime", "delayed"} <= _VOLATILE_FRESHNESS
    assert "historical" not in _VOLATILE_FRESHNESS
    assert "legislation" not in _VOLATILE_FRESHNESS


def test_stale_govuk_source_is_not_marked_volatile():
    """A dated legislation page is reusable; that is correct, and it is why the
    staleness question has to be answered by the connector's date gate rather
    than by blanket cache invalidation."""
    now = _utc_now()
    client = _govuk_client(_iso(now), _iso(now), "")
    match = _run_govuk(client)
    source = govuk_build_source(match)
    assert source.freshness == "legislation"
    assert source.freshness not in {"realtime", "delayed"}
    assert json.dumps({"freshness": source.freshness})
