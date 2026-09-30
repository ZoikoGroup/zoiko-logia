"""Coverage-gap connectors added alongside the live-data expansion.

Covers fx_fallback.py, bank_of_england.py, govuk.py and sec_search.py, the nine
additional FRED series, and the live_data wiring for all of them. The recurring
theme in these tests is refusal: every one of these connectors can produce a
confidently-formatted wrong answer, and a test that only checks the happy path
does not catch that.
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestration.bank_of_england import (
    BankRateMatch, _build_source as _build_boe_source, _definition_for_query as _boe_definition,
    _parse_csv, _requested_start,
)
from app.orchestration.fred import _definition_for_query as _fred_definition
from app.orchestration.fx_fallback import (
    _as_date, _base as _fx_base, _build_source as _build_fx_fallback_source,
    _find_fallback_rates,
)
from app.orchestration.govuk import (
    _build_source as _build_govuk_source, _definition_for_query as _govuk_definition,
    _is_fresh, _strip_html,
)
from app.orchestration.sec_search import (
    FilingHit, PeerRow, _build_fulltext_source, _build_peer_source, _clean_number,
    _periods, _search_phrase, fetch_sec_fulltext, fetch_sec_peer_rank,
)
from app.orchestration.live_data import fetch_live_data

_APPLE = {"title": "Apple Inc.", "ticker": "AAPL", "cik_str": 320193}
_MICROSOFT = {"title": "MICROSOFT CORP", "ticker": "MSFT", "cik_str": 789019}


def _response(text: str = "", payload: object = None) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.text = text
    response.json = MagicMock(return_value=payload)
    return response


# ── fx_fallback ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_never_competes_with_the_official_ecb_rate():
    """The whole design is that this only fills a gap. INR and CHF are ECB
    reference rates, so the fallback must not fire even though those pairs are
    perfectly answerable by the primary."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        assert await _find_fallback_rates("convert 5000 USD to INR") == []
        assert await _find_fallback_rates("convert 5000 GBP to CHF") == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_gates_on_a_gap_and_makes_no_request_otherwise():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        assert await _find_fallback_rates("convert 5000 USD to EUR") == []
        assert await _find_fallback_rates("what is the weather in Paris") == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_fills_a_pair_the_ecnb_cannot_serve():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _rates_response()
        matches = await _find_fallback_rates("convert 5000 USD to AED")

    assert len(matches) == 1
    match = matches[0]
    assert (match.base_cur, match.quote_cur) == ("USD", "AED")
    assert match.rate == pytest.approx(3.6725)
    assert match.converted == pytest.approx(18362.5)
    # One request for the base's whole rate table, regardless of target count.
    assert mock_get.await_count == 1
    assert "/latest/USD" in mock_get.await_args.args[0]


@pytest.mark.asyncio
async def test_fallback_serves_every_gap_pair_in_one_request():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _rates_response()
        matches = await _find_fallback_rates("compare 1 USD to AED, SAR and NGN")

    assert {m.quote_cur for m in matches} == {"AED", "SAR", "NGN"}
    assert mock_get.await_count == 1


def test_fallback_labels_the_rate_as_a_market_rate_not_a_reference_rate():
    """A market aggregator must never be quotable as an official rate. This is
    the distinction the module exists to preserve, so it is asserted on the
    source text rather than left to the model's judgement."""
    source = _build_fx_fallback_source(_rate_match())
    assert "NOT an official central-bank reference rate" in source.snippet
    assert "market rate" in (source.provider or "")
    assert source.freshness == "delayed"
    assert source.observation is not None
    assert source.observation.indicator == "USD/AED exchange rate"


@pytest.mark.asyncio
async def test_fallback_treats_a_provider_reported_error_as_no_data():
    """open.er-api reports its own failures as HTTP 200 with result=error. A
    200 is not evidence that the rates exist."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _response(payload={"result": "error", "error-type": "unsupported-code"})
        assert await _find_fallback_rates("convert 5000 USD to AED") == []


@pytest.mark.asyncio
async def test_fallback_skips_a_target_absent_from_the_rate_table():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _response(payload={"rates": {"EUR": 0.87}, "result": "success"})
        assert await _find_fallback_rates("convert 5000 USD to AED") == []



def test_fallback_labels_the_rate_as_a_market_rate_not_a_reference_rate():
    """A market aggregator must never be quotable as an official rate. This is
    the distinction the module exists to preserve, so it is asserted on the
    source text rather than left to the model's judgement."""
    source = _build_fx_fallback_source(_rate_match())
    assert "NOT an official central-bank reference rate" in source.snippet
    assert "market rate" in (source.provider or "")
    assert source.freshness == "delayed"
    assert source.observation is not None
    assert source.observation.indicator == "USD/AED exchange rate"


@pytest.mark.asyncio
async def test_fallback_treats_a_provider_reported_error_as_no_data():
    """open.er-api reports its own failures as HTTP 200 with result=error. A
    200 is not evidence that the rates exist."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _response(payload={"result": "error", "error-type": "unsupported-code"})
        assert await _find_fallback_rates("convert 5000 USD to AED") == []


@pytest.mark.asyncio
async def test_fallback_skips_a_target_absent_from_the_rate_table():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _response(payload={"rates": {"EUR": 0.87}, "result": "success"})
        assert await _find_fallback_rates("convert 5000 USD to AED") == []


def test_fallback_date_prefers_the_unix_timestamp_over_the_display_string():
    """The display string is RFC 1123 with a weekday prefix. Anchoring at the
    start of it would silently yield nothing and put the raw header on a
    citation, so it is searched rather than matched, and the unix stamp wins."""
    stamp = int(datetime(2026, 3, 4, 22, 30, tzinfo=timezone.utc).timestamp())
    assert _as_date({"time_last_update_unix": stamp, "time_last_update_utc": "Wed, 04 Mar 2026 00:04:01 +0000"}) == "2026-03-04"
    assert _as_date({"time_last_update_utc": "Wed, 04 Mar 2026 00:04:01 +0000"}) == "2026-03-04"
    # Nothing recognisable: the header is returned rather than dropped, because
    # an imprecise date on a good source beats no source.
    assert _as_date({"time_last_update_utc": "whenever"}) == "whenever"
    assert _as_date({}) == ""


def test_malformed_fallback_base_url_falls_back_to_the_known_endpoint(monkeypatch):
    monkeypatch.setenv("OPEN_ER_API_BASE_URL", "https://open.er-api.com/v6OPEN_ER_API_KEY=oops")
    assert _fx_base() == "https://open.er-api.com/v6"


# ── Bank of England ──────────────────────────────────────────────────────────

def test_boe_answers_uk_and_refuses_every_other_country():
    """'US bank rate' and 'India base rate' contain the literal words this
    connector matches on. Returning the UK Bank Rate to either would be a
    well-formatted wrong answer about monetary policy."""
    assert _boe_definition("UK Bank Rate last 3 years") == "IUDBEDR"
    assert _boe_definition("what is the current Bank Rate") == "IUDBEDR"
    assert _boe_definition("UK base rate since 2020") == "IUDBEDR"
    assert _boe_definition("US bank rate") is None
    assert _boe_definition("India base rate") is None
    assert _boe_definition("eurozone policy rate") is None
    # No rate wording at all.
    assert _boe_definition("UK unemployment") is None


def test_boe_rejects_the_html_error_page_iadb_returns_with_http_200():
    """IADB answers an unknown SeriesCodes with a 200 and an HTML page. Parsing
    that as data would put a whole page of navigation in a Bank Rate series."""
    assert _parse_csv("<html><body>Series code not found</body></html>", "IUDBEDR") == []
    assert _parse_csv("", "IUDBEDR") == []


def test_boe_skips_rate_free_days_rather_than_plotting_zero():
    parsed = _parse_csv(
        "DATE,IUDBEDR\n"
        "01 Jan 2026,4.75\n"
        "02 Jan 2026,.\n"
        "03 Jan 2026,NA\n"
        "04 Jan 2026,4.75\n"
        "05 Jan 2026,4.5\n",
        "IUDBEDR",
    )
    assert parsed == [
        ("2026-01-01", 4.75),
        ("2026-01-04", 4.75),
        ("2026-01-05", 4.5),
    ]


def test_boe_reports_the_most_recent_move_in_the_rate():
    """The Bank Rate can sit at one value for a year and then move twice in a
    quarter. A flat point series hides that, so the source says it explicitly."""
    source = _build_boe_source(BankRateMatch(
        series_id="IUDBEDR", series_name="UK Bank Rate",
        points=[("2025-01-01", 4.5), ("2025-06-19", 4.5), ("2025-12-18", 4.25)],
        unit="%", url="https://www.bankofengland.co.uk/boeapps/database/bank-rate",
        latest_change=("2025-06-19", "2025-12-18", -0.25),
    ))
    assert "moved down 0.25 percentage points on 2025-12-18" in source.snippet
    assert "2025-12-18: 4.25%" in source.snippet
    assert "United Kingdom" in source.snippet
    assert source.series is not None and len(source.series) == 3


def test_boe_handles_leap_day_spans_and_spelled_numbers():
    today = date(2026, 8, 21)
    assert _requested_start("UK Bank Rate over the last 3 years", today=today) == "21/Aug/2023"
    assert _requested_start("UK Bank Rate last five years", today=today) == "21/Aug/2021"
    assert _requested_start("UK Bank Rate", today=today) is None
    # 29 Feb has no 2023 counterpart, so the window has to land on the 28th
    # rather than raise and lose the whole series.
    assert _requested_start("UK Bank Rate over the last 1 year", today=date(2024, 2, 29)) == "28/Feb/2023"


# ── GOV.UK ───────────────────────────────────────────────────────────────────

def test_govuk_gating_requires_a_topic_a_rate_and_a_currentness_intent():
    assert _govuk_definition("what is the current UK VAT rate") is not None
    assert _govuk_definition("current UK corporation tax rate") is not None
    # No rate wording: a question about how a regime works is not a rate lookup.
    assert _govuk_definition("how does VAT work") is None
    # No currentness intent.
    assert _govuk_definition("UK VAT rates") is None
    # Not a UK tax topic.
    assert _govuk_definition("what is the current Irish VAT rate") is None


def test_govuk_refuses_another_country_rather_than_answering_with_uk_rates():
    """'What is the current German VAT rate' matches the VAT topic, the rate
    wording and the currentness intent all at once. Without the scope check it
    is answered with the UK VAT page: a real official rate, for the wrong
    country — the hardest kind of wrong to spot in an answer."""
    assert _govuk_definition("what is the current German VAT rate") is None
    assert _govuk_definition("what are the current US corporation tax rates") is None
    assert _govuk_definition("current French income tax rates") is None
    # Naming the UK alongside another country is not an "about the UK" question.
    assert _govuk_definition("compare UK and German VAT rates") is None
    # Naming the UK alone is.
    assert _govuk_definition("what is the current UK VAT rate") is not None


def test_govuk_treats_an_absent_or_unparseable_date_as_stale():
    """A page that will not say when it was last checked is not evidence of a
    current rate. This is the whole guard: GOV.UK never deletes a page, it
    republishes the slug and leaves the old one answering 200 forever."""
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert _is_fresh("2026-07-10T09:00:00+01:00", now=now) is True
    assert _is_fresh("2015-07-08T09:00:00+01:00", now=now) is False
    assert _is_fresh(None, now=now) is False
    assert _is_fresh("", now=now) is False
    assert _is_fresh("not a date", now=now) is False


def test_govuk_max_age_is_configurable_and_survives_a_bad_value(monkeypatch):
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    # ~20 months old: stale at the 12-month default, fresh at 36.
    assert _is_fresh("2025-01-08T09:00:00+01:00", now=now) is False
    monkeypatch.setenv("GOVUK_MAX_AGE_MONTHS", "36")
    assert _is_fresh("2025-01-08T09:00:00+01:00", now=now) is True
    # Unparseable and out-of-range values fall back to 12 rather than raising
    # or, worse, accepting an unbounded window.
    for bad in ("not-a-number", "0", "-3", "2400"):
        monkeypatch.setenv("GOVUK_MAX_AGE_MONTHS", bad)
        assert _is_fresh("2015-07-08T09:00:00+01:00", now=now) is False


def test_govuk_source_states_its_own_last_updated_date():
    source = _build_govuk_source(_govuk_match())
    assert "last updated by GOV.UK on 2026-07-10" in source.snippet
    assert "updated 2026-07-10" in source.title
    assert source.observation is not None
    assert source.observation.value == "2026-07-10"


def test_govuk_strips_markup_into_readable_text():
    """This text is quoted into a model prompt as the official wording, so the
    spacing that inline tags leave behind is tidied rather than shipped."""
    text = _strip_html("<p>Standard rate is <strong>20%</strong>.</p><li>Zero 0%</li>")
    assert "Standard rate is 20%." in text
    assert "<" not in text
    assert "20% ." not in text
    assert _strip_html("<p>Relief is ( 5 points ).</p>") == "Relief is (5 points)."


# ── SEC full-text search ──────────────────────────────────────────────────────

def test_search_phrase_strips_the_company_name_including_the_possessive():
    """EDGAR's index is an exact full-text matcher. A leftover token is fatal:
    'Apple's supply chain' matches nothing at all, while 'supply chain'
    matches filings. The company's own name is the most common such token."""
    assert _search_phrase("What are Apple's risk factors about supply chain?", _APPLE) == "supply chain"
    assert _search_phrase("Microsoft legal proceedings", _MICROSOFT) == "legal proceedings"
    assert _search_phrase("AAPL competition", _APPLE) == "competition"


def test_search_phrase_falls_back_to_the_section_named_in_the_question():
    assert _search_phrase("Microsoft legal proceedings", _MICROSOFT) == "legal proceedings"
    assert _search_phrase("Apple internal controls", _APPLE) == "internal control"
    assert _search_phrase("Tesla MD&A", {"title": "Tesla, Inc.", "ticker": "TSLA", "cik_str": 1318605}) == "management's discussion"


def test_an_explicit_topic_beats_the_section_it_sits_in():
    """'Apple cybersecurity risk factors' is a question about cybersecurity.
    Falling back to the section name would answer a different question."""
    assert _search_phrase("Apple cybersecurity risk factors", _APPLE) == "cybersecurity"


def test_search_phrase_returns_none_when_nothing_is_left():
    """A question that is only a company and a section has no topic beyond the
    section, so it is None only when even the section is gone."""
    assert _search_phrase("What does Apple say", _APPLE) is None
    assert _search_phrase("Tell me about Microsoft", _MICROSOFT) is None


def test_fulltext_gate_keeps_it_off_ordinary_questions():
    assert _FULLTEXT_HINT_OK("What is Apple's share price?") is False
    assert _FULLTEXT_HINT_OK("Apple net income") is False
    assert _FULLTEXT_HINT_OK("What are Apple's risk factors about supply chain?") is True


@pytest.mark.asyncio
async def test_fulltext_requires_an_identifying_user_agent(monkeypatch):
    monkeypatch.setattr("app.orchestration.sec_search._user_agent", lambda: "")
    assert await fetch_sec_fulltext("What are Apple's risk factors about supply chain?") == []


@pytest.mark.asyncio
async def test_fulltext_gives_up_for_a_company_edgar_does_not_file_for(monkeypatch):
    monkeypatch.setattr("app.orchestration.sec_search._user_agent", lambda: "Kriton test@example.com")
    monkeypatch.setattr("app.orchestration.sec_search._load_registrants", AsyncMock(return_value=[_APPLE]))
    monkeypatch.setattr("app.orchestration.sec_search.resolve_company", lambda query, registrants: None)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        assert await fetch_sec_fulltext("Tesco legal proceedings") == []
    mock_get.assert_not_called()


def test_fulltext_source_sorts_by_recency_not_relevance():
    """EDGAR returns relevance order, which surfaces a 2010 10-K/A above a
    current filing. A question about what a company SAYS means what it says
    now."""
    source = _build_fulltext_source("supply chain", [
        FilingHit("Apple Inc.", 320193, "10-K", "2025-10-31", "0000320193-25-000079", "aapl-20250927"),
        FilingHit("Apple Inc.", 320193, "10-K", "2010-11-30", "0000320193-10-000052", "aapl-20101030"),
    ])
    assert "filed 2025-10-31" in source.snippet
    assert source.snippet.index("2025-10-31") < source.snippet.index("2010-11-30")
    assert "has not been reproduced here" in source.snippet


# ── SEC XBRL peer ranking ─────────────────────────────────────────────────────

def test_an_explicit_year_is_never_silently_replaced():
    """Asking for 2023 must not answer with 2022. The fallback years exist only
    to cover a frame that is genuinely empty, and only when none was asked for."""
    assert _periods("which companies spent the most on R&D in 2023") == ["CY2023", "CY2023Q4I"]


def test_frame_lookup_covers_instant_concepts():
    """Total Assets is a balance-sheet position, not a year of activity. Its
    frame is CY2024Q4I; asking for CY2024 returns nothing at all, silently."""
    frames = _periods("who has the highest total assets")
    assert any(frame.endswith("I") for frame in frames)
    assert all(frame.startswith("CY") for frame in frames)


def test_peer_source_labels_an_instant_as_a_balance_not_a_period():
    instant = _build_peer_source("Total assets", "Assets", "CY2025Q4I", [
        PeerRow("APPLE INC", 320193, 3.6e11, "", "2025-09-27", "0000320193-25-000079"),
    ])
    assert "BALANCE as at a point in time" in instant.snippet
    duration = _build_peer_source("Revenue", "Revenues", "CY2023", [
        PeerRow("APPLE INC", 320193, 4.0e11, "2022-09-25", "2023-09-30", "0000320193-23-000106"),
    ])
    assert "periods DIFFER" in duration.snippet
    assert "BALANCE" not in duration.snippet


def test_peer_source_puts_each_registrant_s_own_period_on_every_row():
    """CY2023 is the annual period a registrant filed that OVERLAPS 2023, so
    Walmart's row is Feb 2023-Jan 2024 and Apple's is Sep 2022-Sep 2023.
    Presenting those as like-for-like annual figures would be wrong at the top
    of the table, and wrong in the direction that looks authoritative."""
    source = _build_peer_source("Revenue", "Revenues", "CY2023", [
        PeerRow("Walmart Inc.", 104169, 6.4e12, "2023-02-01", "2024-01-31", "0000104169-24-000021"),
        PeerRow("Apple Inc.", 320193, 4.0e11, "2022-09-25", "2023-09-30", "0000320193-23-000106"),
    ])
    assert "2023-02-01 to 2024-01-31" in source.snippet
    assert "2022-09-25 to 2023-09-30" in source.snippet
    assert "$6.40 trillion" in source.snippet
    assert "1. Walmart Inc." in source.snippet and "2. Apple Inc." in source.snippet


def test_peer_gate_keeps_it_off_single_company_and_non_us_questions():
    from app.orchestration.sec_search import _concept_for

    # No cross-company wording: this is a question about one registrant, and
    # sec_edgar.py already answers it from that company's own filings.
    assert _PEER_HINT_OK("Apple net income") is False
    # Cross-company wording, but nothing in the concept registry names a metric,
    # so there is no tag to rank on. "compare" alone must not manufacture a
    # ranking of UK inflation out of US XBRL tags.
    assert _PEER_HINT_OK("compare UK inflation") is True
    assert _concept_for("compare UK inflation") is None
    assert _concept_for("which US companies spend the most on R&D") is not None
    assert _PEER_HINT_OK("who has the highest total assets") is True
    assert _PEER_HINT_OK("which US companies spend the most on R&D") is True


def test_clean_number_reads_as_a_person_would_say_it():
    assert _clean_number(6_400_000_000_000) == "6.40 trillion"
    assert _clean_number(-2_500_000_000) == "-2.50 billion"
    assert _clean_number(1_234_000) == "1.23 million"
    assert _clean_number(842) == "842"


@pytest.mark.asyncio
async def test_peer_rank_gives_up_when_the_frame_is_empty(monkeypatch):
    """An empty frame must produce no source, not an empty ranking that reads
    as 'these companies reported nothing'."""
    monkeypatch.setattr("app.orchestration.sec_search._user_agent", lambda: "Kriton test@example.com")
    with patch("app.orchestration.sec_search._fetch_frame", AsyncMock(return_value=[])) as frame:
        assert await fetch_sec_peer_rank("which US companies have the highest total assets") == []
    assert frame.await_count > 0


# ── FRED additions ───────────────────────────────────────────────────────────

def test_the_nine_added_fred_series_resolve(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    cases = {
        "US 10 year breakeven inflation rate": "T10YIE",
        "US core PCE inflation last 2 years": "PCEPILFE",
        "US yield curve last 2 years": "T10Y2Y",
        "US 2 year treasury rate": "DGS2",
        "US 30 year treasury rate": "DGS30",
        "US 30 year mortgage rate": "MORTGAGE30US",
        "US high yield bond spread": "BAMLH0A0HYM2",
        "US industrial production last 2 years": "INDPRO",
        "US retail sales last 2 years": "RSXFS",
    }
    for query, series_id in cases.items():
        definition = _fred_definition(query)
        assert definition is not None, query
        assert definition.series_id == series_id, query


def test_fred_still_refuses_a_non_us_country(monkeypatch):
    """The implicit-US shortcut is only for series whose very name makes them
    US Treasury data. 'India retail sales' must not resolve to the US RSXFS,
    and 'industrial production' is phrased about other countries too often to
    assume — so those two require the country to be named."""
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _fred_definition("India retail sales last 3 years") is None
    assert _fred_definition("German industrial production") is None
    assert _fred_definition("Japan retail sales") is None
    # Naming the US works, and so does a Treasury series with no country named
    # because nothing else could mean it.
    assert _fred_definition("US retail sales last 2 years") is not None
    assert _fred_definition("US industrial production last 2 years") is not None
    assert _fred_definition("show the 2 year treasury rate") is not None


# ── live_data wiring ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_data_prefers_the_central_bank_rate_over_the_market_fallback(monkeypatch):
    """When both can answer, the ECB reference rate is the one that must reach
    the user. The fallback fills, it never competes."""
    from app.orchestration.frankfurter import RateMatch

    primary = RateMatch(
        base_cur="USD", quote_cur="INR", rate=83.2, amount=5000,
        converted=416000, date="2026-09-28", url="https://api.frankfurter.app/latest?from=USD",
    )
    fallback = RateMatch(
        base_cur="USD", quote_cur="AED", rate=3.6725, amount=5000,
        converted=18362.5, date="2026-09-29", url="https://open.er-api.com/v6/latest/USD",
    )
    with (
        patch("app.orchestration.live_data._find_rate", new_callable=AsyncMock, return_value=primary),
        patch("app.orchestration.live_data._find_fallback_rate", new_callable=AsyncMock, return_value=fallback),
    ):
        result = await fetch_live_data("convert 5000 USD to INR")

    assert len(result.sources) == 1
    assert "Frankfurter" in (result.sources[0].provider or "")
    assert [point.value for point in result.evidence.observations] == [83.2]


@pytest.mark.asyncio
async def test_live_data_uses_the_fallback_only_when_the_primary_cannot_answer(monkeypatch):
    from app.orchestration.frankfurter import RateMatch

    fallback = RateMatch(
        base_cur="USD", quote_cur="AED", rate=3.6725, amount=5000,
        converted=18362.5, date="2026-09-29", url="https://open.er-api.com/v6/latest/USD",
    )
    with (
        patch("app.orchestration.live_data._find_rate", new_callable=AsyncMock, return_value=None),
        patch("app.orchestration.live_data._find_fallback_rate", new_callable=AsyncMock, return_value=fallback),
    ):
        result = await fetch_live_data("convert 5000 USD to AED")

    assert len(result.sources) == 1
    assert "open.er-api.com" in (result.sources[0].provider or "")
    assert result.evidence.subject == "USD/AED exchange rate"
    assert [point.value for point in result.evidence.observations] == [3.6725]


@pytest.mark.asyncio
async def test_live_data_adds_the_boe_series_to_chart_evidence(monkeypatch):
    match = BankRateMatch(
        series_id="IUDBEDR", series_name="UK Bank Rate",
        points=[("2026-01-01", 4.5), ("2026-02-01", 4.25)],
        unit="%", url="https://www.bankofengland.co.uk/boeapps/database/bank-rate",
    )
    with patch("app.orchestration.live_data._find_bank_rate", new_callable=AsyncMock, return_value=match):
        result = await fetch_live_data("UK Bank Rate last 3 years")

    assert result.evidence.subject == "UK Bank Rate"
    assert [point.value for point in result.evidence.observations] == [4.5, 4.25]
    assert result.evidence.units == ["%"]


@pytest.mark.asyncio
async def test_live_data_omits_a_stale_govuk_page_entirely(monkeypatch):
    """The corporation tax page answers 200 with 2015 rates on it. If this
    connector ever stops refusing it, the model reports 19% as the current UK
    corporation tax main rate."""
    with patch("app.orchestration.live_data._find_uk_tax_rate", new_callable=AsyncMock, return_value=None):
        result = await fetch_live_data("what is the UK corporation tax rate")
    assert not [s for s in result.sources if (s.provider or "") == "GOV.UK"]


@pytest.mark.asyncio
async def test_live_data_attaches_sec_search_sources_without_inventing_observations(monkeypatch):
    """A full-text hit is a LOCATION in a filing and a peer table is a ranking
    of differently-dated windows. Neither is a single (period, value) series,
    so neither may populate chart evidence."""
    text_source = _build_fulltext_source("supply chain", [
        FilingHit("Apple Inc.", 320193, "10-K", "2025-10-31", "0000320193-25-000079", "aapl-20250927"),
    ])
    peer_source = _build_peer_source("Revenue", "Revenues", "CY2023", [
        PeerRow("Apple Inc.", 320193, 4.0e11, "2022-09-25", "2023-09-30", "0000320193-23-000106"),
    ])
    with (
        patch("app.orchestration.live_data.fetch_sec_fulltext", new_callable=AsyncMock, return_value=[text_source]),
        patch("app.orchestration.live_data.fetch_sec_peer_rank", new_callable=AsyncMock, return_value=[peer_source]),
    ):
        result = await fetch_live_data("which US companies reported the most revenue in 2023")

    assert [s.title for s in result.sources] == [text_source.title, peer_source.title]
    assert result.evidence.observations == []


@pytest.mark.asyncio
async def test_live_data_stays_silent_for_a_concept_question(monkeypatch):
    """No connector here should fire on a definition."""
    result = await fetch_live_data("What is accrual accounting?")
    assert result.sources == [] or all(
        (s.provider or "") not in {
            "open.er-api.com (market rate)", "Bank of England", "GOV.UK", "SEC EDGAR",
            "Federal Reserve Bank of St. Louis (FRED)",
        }
        for s in result.sources
    )


# ── helpers ──────────────────────────────────────────────────────────────────

def _rates_response() -> MagicMock:
    return _response(payload={
        "result": "success",
        "time_last_update_unix": int(
            datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc).timestamp(),
        ),
        "rates": {"AED": 3.6725, "NGN": 1792.923045, "SAR": 3.75, "EGP": 52.070874},
    })


def _rate_match():
    from app.orchestration.frankfurter import RateMatch

    return RateMatch(
        base_cur="USD", quote_cur="AED", rate=3.6725, amount=5000,
        converted=18362.5, date="2026-09-29", url="https://open.er-api.com/v6/latest/USD",
    )


def _govuk_match():
    from app.orchestration.govuk import GovUkMatch

    return GovUkMatch(
        title="VAT rates on different goods and services",
        path="/vat-rates", updated_at="2026-07-10T09:00:00+01:00",
        body="The standard rate of VAT is 20%. " * 20,
        url="https://www.gov.uk/vat-rates",
    )


def _FULLTEXT_HINT_OK(query: str) -> bool:
    from app.orchestration.sec_search import _FULLTEXT_HINT

    return bool(_FULLTEXT_HINT.search(query or ""))


def _PEER_HINT_OK(query: str) -> bool:
    from app.orchestration.sec_search import _PEER_HINT

    return bool(_PEER_HINT.search(query or ""))
