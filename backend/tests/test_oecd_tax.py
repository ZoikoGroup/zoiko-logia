"""OECD statutory corporate income tax rates, via DBnomics.

The happy path for this connector is easy — one number, one year, one country.
What needs testing is everything that can make it wrong: quoting the central
rate for a question that asked for the all-in rate (the two differ by 14 points
in Germany), citing a source page that does not contain the quoted figure,
answering with last year's rate as though it were in force, and treating the
measure's own name — CIT — as a ticker and refusing the question.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestration.oecd_tax import (
    _COMBINED_SERIES,
    _CENTRAL_SERIES,
    _build_source,
    _country_for_query,
    _find_oecd_tax_rate,
    _names_a_company,
)

YEAR = datetime.now(timezone.utc).year

# Verified live against the OECD dataset (2026 values; India and China publish
# one year behind, which the max-age rule accommodates rather than assumes away).
# Keyed by the dataset's ISO3 REF_AREA code, which is what the series id carries.
CENTRAL_VALUES = {
    "USA": (21.0, 25.0), "GBR": (25.0, 25.0), "IRL": (12.5, 12.5), "CAN": (15.0, 15.0),
    "AUS": (30.0, 30.0), "DEU": (15.825, 15.825), "FRA": (36.13, 36.13),
    "JPN": (23.2, 23.2), "IND": (25.17, 24.0), "CHN": (25.0, 25.0),
}
COMBINED_VALUES = {
    "USA": (25.5285, 25.6), "GBR": (25.0, 25.0), "IRL": (12.5, 12.5), "CAN": (26.0, 26.0),
    "AUS": (30.0, 30.0), "DEU": (30.133026, 30.0), "FRA": (36.13, 36.13),
    "JPN": (29.74, 29.74), "IND": (25.17, 24.0), "CHN": (25.0, 25.0),
}


def _payload(series_code: str) -> object:
    iso3 = str(series_code).split(".")[0]
    values = COMBINED_VALUES if ".CIT_C." in series_code else CENTRAL_VALUES
    current, prior = values[iso3]
    return {"series": {"docs": [{
        "period": [f"{YEAR - 1}-01-01", f"{YEAR}-01-01"],
        "value": [prior, current],
    }]}}


def _client() -> MagicMock:
    client = MagicMock()

    async def get(url: str, *args, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(
            return_value=_payload(str(url).rsplit("/", 1)[-1])
        )
        return response

    client.get = get
    return client


@pytest.fixture(autouse=True)
def _current_window(monkeypatch):
    """Pin the freshness window to the current year only, so the fixture years
    do not have to be rewritten every January and a stale fixture cannot pass."""
    monkeypatch.setenv("OECD_TAX_MAX_AGE_YEARS", "0")


_COUNTRY_WORDS = {
    "US": "the United States", "GB": "the UK", "IE": "Ireland", "CA": "Canada",
    "AU": "Australia", "DE": "Germany", "FR": "France", "JP": "Japan",
    "IN": "India", "CN": "China",
}


def test_every_supported_country_is_reachable():
    for iso2, phrase in _COUNTRY_WORDS.items():
        assert _country_for_query(f"corporate tax rate in {phrase}") == iso2


@pytest.mark.parametrize("query", [
    "What is the New Zealand corporate tax rate?",
    "What is the Luxembourg corporate tax rate?",
    "What is the Brazilian corporate tax rate?",
    "What is the corporate tax rate in the eurozone?",
])
def test_countries_outside_the_supported_ten_are_refused(query):
    """The regression: an unsupported country was indistinguishable from naming
    no country, so the default answered for the United States."""
    assert _country_for_query(query) is None
    assert _names_a_company(query) is False


def test_two_supported_countries_in_one_question_are_refused():
    assert _country_for_query("Compare the US and Canadian corporate tax rate") is None
    assert _country_for_query("corporate tax rate in India and the UK") is None


def test_no_country_named_defaults_to_the_united_states():
    assert _country_for_query("What is the corporate tax rate?") == "US"


def test_company_questions_are_refused():
    assert _names_a_company("What is Apple's tax rate?") is True
    assert _names_a_company("What is Microsoft's effective tax rate?") is True


def test_the_measure_name_is_not_read_as_a_ticker():
    """CIT is the dataset's own abbreviation for corporate income tax, and also a
    plausible ticker shape. Reading the question as a company question refused
    "What is the CIT rate in France?" — a tax question about France."""
    assert _names_a_company("What is the CIT rate in France?") is False
    assert _names_a_company("What is the CIT rate?") is False
    assert _country_for_query("What is the CIT rate in France?") == "FR"


async def test_central_government_is_the_default_headline():
    match = await _find_oecd_tax_rate(
        "What is the German corporate tax rate?", client=_client()
    )
    assert match is not None
    assert match.country == "DE"
    assert match.headline == "central"
    assert match.rate == pytest.approx(15.825)
    assert match.other_rate == pytest.approx(30.133026)


@pytest.mark.parametrize("query", [
    "What is the combined corporate tax rate in Germany?",
    "What is the all-in corporate tax rate in Germany?",
    "What is the German corporate tax rate including trade tax?",
])
async def test_questions_about_the_all_in_rate_get_the_combined_headline(query):
    match = await _find_oecd_tax_rate(query, client=_client())
    assert match is not None
    assert match.headline == "combined"
    assert match.rate == pytest.approx(30.133026)
    assert match.other_rate == pytest.approx(15.825)


async def test_the_cited_source_contains_the_quoted_figure():
    """A central-rate answer must not cite the combined series: the reader follows
    the link and finds 30.133% for a question that asked for 15.825%."""
    match = await _find_oecd_tax_rate(
        "What is the German corporate tax rate?", client=_client()
    )
    assert match.url.endswith(_CENTRAL_SERIES.format(iso3="DEU"))
    assert match.other_url.endswith(_COMBINED_SERIES.format(iso3="DEU"))

    combined = await _find_oecd_tax_rate(
        "What is the combined corporate tax rate in Germany?", client=_client()
    )
    assert combined.url.endswith(_COMBINED_SERIES.format(iso3="DEU"))


def test_the_source_states_both_measures_with_their_years():
    from app.orchestration.oecd_tax import OecdTaxMatch

    match = OecdTaxMatch(
        country="DE", headline="central", rate=15.825, year=f"{YEAR}-01-01",
        points=[(f"{YEAR}-01-01", 15.825)], other_rate=30.133026,
        other_year=f"{YEAR}-01-01", other_points=[(f"{YEAR}-01-01", 30.133026)],
        url=f"https://api.db.nomics.world/v22/series/OECD/DSD_TAX_CIT@DF_CIT/"
            + _CENTRAL_SERIES.format(iso3="DEU"),
    )
    source = _build_source(match)
    assert f"{match.rate:g}" in source.snippet
    assert f"{match.other_rate:g}" in source.snippet
    assert "central government" in source.snippet
    assert "combined statutory corporate income tax rate" in source.snippet
    assert source.freshness == "annual"
    assert source.observation.value == f"{match.rate:g}"
    assert source.observation.period == f"{YEAR}-01-01"
    assert source.url == match.url
    assert "Germany" in source.title


async def test_stale_rates_are_refused_rather_than_reported():
    client = MagicMock()

    async def get(url: str, *args, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(return_value={"series": {"docs": [{
            "period": [f"{YEAR - 4}-01-01", f"{YEAR - 3}-01-01"],
            "value": [21.0, 21.0],
        }]}})
        return response

    client.get = get
    assert await _find_oecd_tax_rate(
        "What is the US corporate tax rate?", client=client
    ) is None


async def test_a_null_observation_is_missing_not_a_zero_rate():
    client = MagicMock()

    async def get(url: str, *args, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(return_value={"series": {"docs": [{
            "period": [f"{YEAR - 1}-01-01", f"{YEAR}-01-01", f"{YEAR + 1}-01-01"],
            "value": [None, 21.0, 22.0],
        }]}})
        return response

    client.get = get
    match = await _find_oecd_tax_rate(
        "What is the US corporate tax rate?", client=client
    )
    assert match is not None
    assert match.points == [(f"{YEAR}-01-01", 21.0)]
    assert match.rate == 21.0


async def test_a_rate_for_a_year_that_has_not_happened_is_not_the_rate_in_force():
    """The newest value is what the answer states as current, so a future-dated
    observation would be reported as a rate in force for a year that has not
    arrived."""
    client = MagicMock()

    async def get(url: str, *args, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(return_value={"series": {"docs": [{
            "period": [f"{YEAR}-01-01", f"{YEAR + 1}-01-01"],
            "value": [21.0, 99.0],
        }]}})
        return response

    client.get = get
    match = await _find_oecd_tax_rate(
        "What is the US corporate tax rate?", client=client
    )
    assert match is not None
    assert match.rate == 21.0
    assert match.year == f"{YEAR}-01-01"


async def test_questions_that_are_not_about_a_rate_are_not_answered():
    for query in (
        "How is corporate tax calculated in Germany?",
        "Corporate tax reform in France",
        "What is the German corporate tax revenue?",
    ):
        assert await _find_oecd_tax_rate(query, client=_client()) is None


async def test_live_data_reports_the_oecd_rate_as_an_annual_observation():
    from app.orchestration.oecd_tax import OecdTaxMatch
    from app.orchestration.live_data import fetch_live_data

    match = OecdTaxMatch(
        country="DE", headline="central", rate=15.825, year=f"{YEAR}-01-01",
        points=[(f"{YEAR - 1}-01-01", 15.0), (f"{YEAR}-01-01", 15.825)],
        other_rate=30.133026, other_year=f"{YEAR}-01-01",
        other_points=[(f"{YEAR}-01-01", 30.133026)],
        url="https://api.db.nomics.world/v22/series/OECD/DSD_TAX_CIT@DF_CIT/DEU.A.CIT.ST.PT_INC_TAX.S1311._Z._Z._Z",
    )
    with patch("app.orchestration.live_data._find_oecd_tax_rate",
               new_callable=AsyncMock, return_value=match), \
         patch("app.orchestration.live_data._find_fred_series",
               new_callable=AsyncMock, return_value=None), \
         patch("app.orchestration.live_data._find_policy_rate",
               new_callable=AsyncMock, return_value=None), \
         patch("app.orchestration.live_data._find_bank_rate",
               new_callable=AsyncMock, return_value=None), \
         patch("app.orchestration.live_data._find_cash_rate",
               new_callable=AsyncMock, return_value=None), \
         patch("app.orchestration.live_data._find_best_series",
               new_callable=AsyncMock, return_value=None), \
         patch("app.orchestration.live_data._find_two_series",
               new_callable=AsyncMock, return_value=None):
        result = await fetch_live_data("What is the German corporate tax rate?")

    assert any(source.provider == "OECD Tax Database" for source in result.sources)
    assert result.evidence.provider == "OECD Tax Database"
    assert result.evidence.series_id == "oecd_cit_de"
    assert [point.value for point in result.evidence.observations] == [15.0, 15.825]
    assert {point.measure for point in result.evidence.observations} == {
        "statutory corporate income tax rate (%)"
    }
    assert "statutory corporate income tax rate (%)" in result.evidence.measures
