"""Five-country live-data connectors added for the coverage expansion.

Covers bank_of_canada.py, rba.py, abs_australia.py, cso_ireland.py and
us_treasury.py, the index_quote market provider, and the refusal guards that
keep each connector stuck to its own country. The recurring theme is the same
as the coverage-gap tests: every connector here CAN produce a confidently
formatted answer for the wrong economy, and the happy path is the easy part —
the wrong-country answer is what gets tested.
"""
import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.market_data import registry
from app.domains.market_data.identity import resolve_index
from app.domains.market_data.schemas import EntityRef, ProviderBadResponse
from app.orchestration.abs_australia import (
    _definition_for_query as _abs_definition, _parse_abs_csv,
)
from app.orchestration.bank_of_canada import (
    _definition_for_query as _boc_definition, _parse_observations,
)
from app.orchestration.cso_ireland import (
    _definition_for_query as _cso_definition, _normalise_period,
)
from app.orchestration.country_scope import is_country_scoped, named_countries
from app.orchestration.dbnomics import _country_in_query, _series_is_country
from app.orchestration.fred import _definition_for_query as _fred_definition
from app.orchestration.live_data import fetch_live_data
from app.orchestration.rba import (
    _definition_for_query as _rba_definition, _parse_cash_rate,
)
from app.orchestration.us_treasury import (
    _DEBT, _DEFICIT, _REVENUE, _as_float,
    _definition_for_query as _treasury_definition, _fetch_debt, _fetch_mts,
)


def _response(text: str = "", payload: object = None) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.text = text
    response.json = MagicMock(return_value=payload)
    return response


def _client_getting(payload: object = None, text: str = "") -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=_response(text=text, payload=payload))
    return client

def test_named_countries_reports_every_supported_country_in_order():
    assert named_countries("compare Ireland and Australia inflation") == ["IE", "AU"]
    assert named_countries("what is the Canadian policy rate") == ["CA"]
    assert named_countries("no country here") == []


def test_country_scoping_refuses_every_wrong_jurisdiction():
    assert is_country_scoped("what is the Canadian policy rate", "CA") is True
    assert is_country_scoped("how much is the US government debt", "US") is True
    assert is_country_scoped("what is the current UK Bank Rate", "CA") is False
    assert is_country_scoped("US cash rate target", "AU") is False
    assert is_country_scoped("compare UK and Ireland inflation", "IE") is False
    # An unsupported country is a definite request for a different economy.
    assert is_country_scoped("french inflation", "CA") is False


def test_every_country_outside_the_supported_ten_is_recognised():
    """A country missing from this list is indistinguishable from naming no
    country at all, so every connector's default fires: "What is the New Zealand
    inflation rate?" was answered with the Irish CPI and the Australian CPI, and
    "What is the Luxembourg policy rate?" with four countries' policy rates at
    once. Each entry is checked on its own so that one entry being malformed
    cannot hide behind a neighbouring one — the list is built by concatenating
    per-region fragments, and a missing separator welds two countries into a
    single alternative that matches neither.
    """
    from app.orchestration.country_scope import names_another_country

    for country in (
        "New Zealand", "Luxembourg", "Brazil", "Saudi Arabia", "eurozone",
        "Singapore", "Qatar", "Jordan", "Mali", "Georgia", "Brunei", "Antigua",
        "Pakistan", "Azerbaijan", "Comoros", "Cook Islands", "Greenland",
        "Liechtenstein", "Estonia", "Eswatini", "Papua New Guinea", "Iceland",
        "Taiwan", "Kazakhstan", "Sri Lanka", "Hong Kong", "Ukraine",
    ):
        assert names_another_country(f"what is the {country} inflation rate") is True, country

    # The ten this product does serve are not "another country": naming them is
    # affirmative, and they are recognised by named_countries() instead.
    for country in (
        "United States", "UK", "Ireland", "Canada", "Australia", "Germany",
        "France", "Japan", "India", "China",
    ):
        assert names_another_country(f"what is the {country} inflation rate") is False, country


# ── FRED foreign-country guard ───────────────────────────────────────────────

def test_fred_refuses_any_named_non_us_country(monkeypatch):
    """FEDFUNDS matches the bare words "policy rate", so before the guard,
    "What is the Canadian policy rate?" was answered with the US federal funds
    rate — a real number, correctly formatted, for the wrong economy."""
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _fred_definition("what is the federal funds rate").series_id == "FEDFUNDS"
    assert _fred_definition("what is the US federal funds rate").series_id == "FEDFUNDS"
    assert _fred_definition("what is the Canadian policy rate") is None
    assert _fred_definition("UK policy rate") is None
    assert _fred_definition("compare US and UK policy rates") is None
    assert _fred_definition("federal funds rate in Canada") is None


# ── US Treasury ──────────────────────────────────────────────────────────────

def test_treasury_definition_stays_with_dollar_figures():
    assert _treasury_definition("how much is the US government debt") is _DEBT
    assert _treasury_definition("what is the US budget deficit") is _DEFICIT
    assert _treasury_definition("US government revenue") is _REVENUE
    assert _treasury_definition("US government receipts last month") is not None
    # Ratio phrasings belong to FRED, always, before any hint is checked.
    assert _treasury_definition("US government debt as a share of GDP") is None
    assert _treasury_definition("what is the deficit relative to GDP") is None
    # And a different country is a refusal, not a US series.
    assert _treasury_definition("UK government debt") is None
    assert _treasury_definition("canada government debt") is None


@pytest.mark.asyncio
async def test_treasury_mts_accepts_only_discrete_monthly_rows():
    """Table 1 mixes three kinds of row: "D" discrete monthly, "T" a Year-to-
    Date CUMULATIVE figure, and "S" a prior-fiscal-year snapshot. The T row is
    $3.74 trillion against a $198 billion monthly figure — taking it would put
    a cumulative number in a monthly series with nothing about the response
    looking wrong."""
    payload = {"data": [
        {"record_date": "2026-08-31", "classification_desc": "August",
         "current_month_dfct_sur_amt": "-198000000000", "data_type_cd": "D"},
        {"record_date": "2026-08-31", "classification_desc": "August",
         "current_month_dfct_sur_amt": "-3740000000000", "data_type_cd": "T"},
        {"record_date": "2026-08-31", "classification_desc": "August",
         "current_month_dfct_sur_amt": "-1000000000000", "data_type_cd": "S"},
        {"record_date": "2026-07-31", "classification_desc": "July",
         "current_month_dfct_sur_amt": "-183000000000", "data_type_cd": "D"},
        {"record_date": "2026-06-30", "classification_desc": "June",
         "current_month_dfct_sur_amt": "111000000000", "data_type_cd": "D"},
        # A month no one has reported yet: present, labelled, no value.
        {"record_date": "2026-08-31", "classification_desc": "September",
         "current_month_dfct_sur_amt": "null", "data_type_cd": "D"},
    ]}

    match = await _fetch_mts(_client_getting(payload=payload), _DEFICIT)

    assert match is not None
    assert match.points == [
        ("2026-06-30", 111000000000.0),
        ("2026-07-31", -183000000000.0),
        ("2026-08-31", -198000000000.0),
    ]
    assert match.value == -198000000000.0
    # The fiscal-month label travels with its own row; the sort and the label
    # can no longer disagree about which month this is.
    assert match.period_label == (
        "August of fiscal year 2026, reporting period ending 2026-08-31"
    )


@pytest.mark.asyncio
async def test_treasury_debt_skips_non_publication_days():
    payload = {"data": [
        {"record_date": "2026-09-29", "tot_pub_debt_out_amt": "35300000000000"},
        # the file genuinely publishes "null" on federal holidays
        {"record_date": "2026-09-28", "tot_pub_debt_out_amt": "null"},
        {"record_date": "2026-09-25", "tot_pub_debt_out_amt": "35250000000000"},
    ]}
    match = await _fetch_debt(_client_getting(payload=payload), _DEBT)
    assert match is not None
    assert match.value == 35300000000000.0
    assert match.points[0][0] == "2026-09-25"


def test_treasury_as_float_accepts_strings_and_rejects_literals():
    assert _as_float("3,400,000,000,000") == 3400000000000.0
    assert _as_float("-198000000000") == -198000000000.0
    assert _as_float("null") is None
    assert _as_float("") is None
    assert _as_float(None) is None
    assert _as_float("nonsense") is None


# ── Bank of Canada ───────────────────────────────────────────────────────────

def test_boc_definition_is_canada_scoped():
    assert _boc_definition("what is the Canadian policy rate") == "V39079"
    assert _boc_definition("Bank of Canada overnight rate") == "V39079"
    assert _boc_definition("US policy rate") is None
    assert _boc_definition("ask about the Irish overnight rate") is None


def test_boc_parser_drops_missing_observations():
    payload = {"observations": [
        {"d": "2026-09-24", "V39079": {"v": "2.25"}},
        {"d": "2026-09-23", "V39079": {"v": "2.25"}},
        {"d": "2026-09-22", "V39079": {"v": "NA"}},
        {"d": "2026-09-21", "V39079": {"v": "2.75"}},
    ]}
    assert list(_parse_observations(payload)) == [
        ("2026-09-24", 2.25), ("2026-09-23", 2.25), ("2026-09-21", 2.75),
    ]
    assert list(_parse_observations({"observations": [{"d": "not-a-date"}]})) == []


# ── Reserve Bank of Australia ────────────────────────────────────────────────

def test_rba_definition_is_australia_scoped():
    assert _rba_definition("what is Australia's cash rate target") is True
    assert _rba_definition("the Australian policy rate") is True
    assert _rba_definition("the US cash rate target") is False


def test_rba_parser_reads_the_header_by_name_not_position():
    """The F1 CSV opens with a six-row preamble, so the header has to be found
    by the "Title" row and the value column by its NAME. Reading by position
    would turn the cash rate into a bond yield the day the RBA adds a column."""
    payload = (
        "F1 Interest Rates and Yields - Money Market\n"
        'Title,Series X,Cash Rate Target,Bond Yield\n'
        "Description,per cent,per cent,per cent\n"
        "Frequency,Daily,Daily,Daily\n"
        "Type,Announced,Observed,Observed\n"
        "Units,%,%,%\n"
        ",\n"
        "25-Sep-2026,.,4.35,4.20\n"
        "24-Sep-2026,,4.35,4.19\n"
        "23-Sep-2026,4.30,4.30,4.18\n"
        "22-Sep-2026,4.30,4.30,.\n"
    )
    parsed = _parse_cash_rate(payload)
    assert parsed == [
        ("2026-09-22", 4.30), ("2026-09-23", 4.30),
        ("2026-09-24", 4.35), ("2026-09-25", 4.35),
    ]


def test_rba_parser_treats_an_error_page_as_no_data():
    assert _parse_cash_rate("<html><body>Service Unavailable</body></html>") == []
    assert _parse_cash_rate("") == []


# ── Australian Bureau of Statistics ──────────────────────────────────────────

def test_abs_definition_is_australia_scoped():
    match_inflation = _abs_definition("what is Australian inflation")
    match_unemployment = _abs_definition("Australian unemployment rate")
    assert match_inflation is not None and "Consumer Price Index" in match_inflation["name"]
    assert match_unemployment is not None and "Unemployment" in match_unemployment["name"]
    assert _abs_definition("Irish inflation") is None
    assert _abs_definition("what is the Canadian unemployment rate") is None


def test_abs_parser_accepts_quarterly_and_monthly_periods():
    payload = (
        "TIME_PERIOD,OBS_VALUE\n"
        "2026-Q2,2.8\n"
        "2026-Q1,2.7\n"
        "2026-03,.\n"
        "2026-02,2.6\n"
    )
    assert _parse_abs_csv(payload) == [
        ("2026-02", 2.6), ("2026-Q1", 2.7), ("2026-Q2", 2.8),
    ]
    assert _parse_abs_csv("TIME_PERIOD,OBS_VALUE\n") == []


# ── Central Statistics Office of Ireland ─────────────────────────────────────

def test_cso_definition_is_ireland_scoped():
    assert _cso_definition("what is the Irish inflation rate") == "CPM01"
    assert _cso_definition("Irish annual inflation rate") == "CPM16"
    assert _cso_definition("what is the UK inflation rate") is None
    assert _cso_definition("Australian CPI") is None


def test_cso_normalises_periods_and_refuses_internal_codes():
    assert _normalise_period("202507") == "2025-07"
    assert _normalise_period("2025Q2") == "2025-Q2"
    assert _normalise_period("2025") == "2025"
    assert _normalise_period("2025M07") is None
    assert _normalise_period("") is None


# ── DBnomics country guard ───────────────────────────────────────────────────

def test_dbnomics_series_must_belong_to_the_named_country():
    assert _country_in_query("what is inflation in Ireland") == "Ireland"
    assert _series_is_country("Ireland - Gross domestic product, current prices", "Ireland") is True
    assert _series_is_country("Australia - Labour Force, unemployment", "Ireland") is False
    assert _series_is_country("Australia - Labour Force, unemployment", "Australia") is True
    # A UK series about Northern Ireland is not an Ireland series.
    assert _series_is_country("Northern Ireland - retail sales", "Ireland") is False
    # No country named: nothing to refuse.
    assert _series_is_country("Labour Force, unemployment", None) is True


# ── Market-data index intent ─────────────────────────────────────────────────

def test_index_intent_fires_for_a_named_benchmark_only():
    assert registry.detect_intent("What is the S&P 500?") == registry.INTENT_INDEX
    assert registry.detect_intent("how is the FTSE 100 doing") == registry.INTENT_INDEX
    assert registry.detect_intent("what is an index?") is None


def test_resolve_index_returns_the_closed_symbol_set():
    assert resolve_index("how is the FTSE 100 today") == ("^FTSE", "FTSE 100", "GB")
    assert resolve_index("the S&P 500 level") == ("^GSPC", "S&P 500", "US")
    assert resolve_index("iseq value this year") == ("^ISEQ", "ISEQ All Shares", "IE")
    assert resolve_index("what is an index") is None


def test_macro_questions_are_gated_out_of_market_intent():
    assert registry._macro_question_refusal("US government revenue") is True
    assert registry._macro_question_refusal("Canada GDP") is True
    assert registry._macro_question_refusal("Apple revenue") is False
    assert registry.detect_intent("US government revenue") is None
    assert registry.detect_intent("Canada GDP") is None
    assert registry.detect_intent("Apple revenue") == registry.INTENT_FUNDAMENTALS


def test_index_provider_refuses_non_index_symbols():
    provider = None
    for candidate in registry.all_providers():
        if candidate.name == "index_quote":
            provider = candidate
            break
    assert provider is not None
    assert provider.name == "index_quote"


@pytest.mark.asyncio
async def test_index_provider_refuses_a_plain_stock_symbol_before_any_request():
    from app.domains.market_data.providers.index_quote import IndexQuoteProvider

    provider = IndexQuoteProvider()
    ref = EntityRef(name="Apple Inc.", ticker="AAPL")
    client = MagicMock()
    client.get = AsyncMock()
    with pytest.raises(ProviderBadResponse):
        await provider.get_quote(client, ref)
    client.get.assert_not_called()


# ── Companies House cross-country guard ──────────────────────────────────────

def test_companies_house_refuses_a_foreign_country_without_a_uk_cue():
    from app.domains.market_data.service import _companies_house_should_refuse

    assert _companies_house_should_refuse("Canada House Limited filings") is True
    assert _companies_house_should_refuse("what are the filings of that Irish company") is True
    assert _companies_house_should_refuse("an Australian company's statutory filings") is True
    assert _companies_house_should_refuse("a US-listed company's filings") is True
    assert _companies_house_should_refuse("Barclays plc filings at Companies House") is False
    assert _companies_house_should_refuse("company 01026167 filings") is False


# ── live_data wiring ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_data_serves_the_canadian_rate_and_not_fred(monkeypatch):
    """The regression this guard exists for: "the Canadian policy rate" had
    been answered with FRED's FEDFUNDS, a US series that matches the bare
    words "policy rate". Answers for Canada must come from Canada."""
    from app.orchestration.bank_of_canada import PolicyRateMatch

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    match = PolicyRateMatch(
        series_id="V39079", series_name="Bank of Canada Policy Interest Rate",
        points=[("2026-06-03", 4.25), ("2026-07-15", 4.5)],
        unit="%", url="https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
    )
    with patch("app.orchestration.live_data._find_policy_rate", new_callable=AsyncMock, return_value=match), \
         patch(
            "app.orchestration.live_data._find_fred_series",
            new_callable=AsyncMock, return_value=None,
         ), \
         patch(
            "app.orchestration.live_data._find_best_series",
            new_callable=AsyncMock, return_value=None,
         ), \
         patch(
            "app.orchestration.live_data._find_two_series",
            new_callable=AsyncMock, return_value=None,
         ):
        result = await fetch_live_data("What is the Canadian policy rate?")

    assert {s.provider for s in result.sources} == {"Bank of Canada"}
    assert result.evidence.subject == "Bank of Canada Policy Interest Rate"
    assert [point.value for point in result.evidence.observations] == [4.25, 4.5]
    assert result.evidence.provider == "Bank of Canada"


@pytest.mark.asyncio
async def test_live_data_adds_the_treasury_dollar_figure(monkeypatch):
    from app.orchestration.us_treasury import TreasuryMatch

    match = TreasuryMatch(
        name="US Federal Monthly Deficit or Surplus", value=-198000000000.0,
        unit="USD", period="2026-08-31",
        period_label="August of fiscal year 2026, reporting period ending 2026-08-31",
        points=[("2026-07-31", -183000000000.0), ("2026-08-31", -198000000000.0)],
        url="https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/operating-cash-balance/mts-table-1",
    )
    with patch(
        "app.orchestration.live_data._find_treasury_figure",
        new_callable=AsyncMock, return_value=match,
    ), patch(
        "app.orchestration.live_data._find_fred_series",
        new_callable=AsyncMock, return_value=None,
    ), patch(
        "app.orchestration.live_data._find_best_series",
        new_callable=AsyncMock, return_value=None,
    ), patch(
        "app.orchestration.live_data._find_two_series",
        new_callable=AsyncMock, return_value=None,
    ):
        result = await fetch_live_data("What is the US budget deficit?")

    assert {s.provider for s in result.sources} == {"U.S. Department of the Treasury"}
    assert result.evidence.subject == "US Federal Monthly Deficit or Surplus"
    assert result.evidence.provider == "U.S. Department of the Treasury"
    # series_id defaults to None, so the guard that lets a later connector fill
    # it in has to test for emptiness rather than compare against "".
    assert result.evidence.series_id == match.name
    assert [point.value for point in result.evidence.observations] == [
        -183000000000.0, -198000000000.0,
    ]