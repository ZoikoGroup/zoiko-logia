from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.orchestration.fred import (
    _definition_for_query, _find_fred_series, _fred_base, _observation_limit,
    _requested_range, fetch_fred_stats,
)
from app.orchestration.live_data import fetch_live_data


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


_PAYLOAD = {
    "observations": [
        {"date": "2024-03-01", "value": "313.207"},
        {"date": "2024-02-01", "value": "."},
        {"date": "2024-01-01", "value": "308.742"},
    ]
}


@pytest.mark.asyncio
async def test_fred_requires_key_and_explicit_us_context(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert await _find_fred_series("Show US CPI") is None

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert await _find_fred_series("Show India CPI") is None


def test_uniquely_us_series_do_not_require_redundant_us_wording(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _definition_for_query("Display the federal funds rate since 1990").series_id == "FEDFUNDS"
    assert _definition_for_query("Show the ten-year Treasury rate").series_id == "DGS10"


def test_fred_recognizes_dotted_us_and_parses_only_explicit_time_spans(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _definition_for_query("Show U.S. GDP") is not None
    assert _observation_limit("Show the U.S. ten-year Treasury rate", "daily") == 90
    assert _observation_limit("Show US CPI over the last ten years", "monthly") == 120


def test_fred_distinguishes_real_gdp_growth_real_level_and_nominal_level(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _definition_for_query("Show US real GDP").series_id == "GDPC1"
    assert _definition_for_query("Show US GDP growth").series_id == "A191RL1Q225SBEA"
    assert _definition_for_query("Show US nominal GDP").series_id == "GDP"
    assert _definition_for_query("Show US GDP").series_id == "GDP"


def test_fred_parses_since_between_ranges_and_relative_years():
    today = date(2026, 8, 21)
    assert _requested_range("Federal funds rate since 1990", today=today) == ("1990-01-01", "2026-08-21")
    assert _requested_range("Unemployment from 2000 to 2020", today=today) == ("2000-01-01", "2020-12-31")
    assert _requested_range("GDP between 2010 and 2015", today=today) == ("2010-01-01", "2015-12-31")
    assert _requested_range("GDP 2018–2022", today=today) == ("2018-01-01", "2022-12-31")
    assert _requested_range("CPI over the last ten years", today=today) == ("2016-08-21", "2026-08-21")


def test_malformed_fred_base_url_falls_back_to_the_official_endpoint(monkeypatch):
    monkeypatch.setenv(
        "FRED_API_BASE_URL",
        "https://api.stlouisfed.org/fredFRED_API_KEY=accidentally-concatenated",
    )
    assert _fred_base() == "https://api.stlouisfed.org/fred"


@pytest.mark.asyncio
async def test_fred_fetches_curated_series_and_skips_missing_values(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _FakeResponse(_PAYLOAD)
        match = await _find_fred_series("Show the US CPI trend")

    assert match is not None
    assert match.series_id == "CPIAUCSL"
    assert match.points == [("2024-01-01", 308.742), ("2024-03-01", 313.207)]
    params = mock_get.await_args.kwargs["params"]
    assert params["api_key"] == "test-key"
    assert params["file_type"] == "json"


@pytest.mark.asyncio
async def test_fred_sends_requested_date_bounds_to_api(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _FakeResponse(_PAYLOAD)
        await _find_fred_series("Show US unemployment since 2000")
    params = mock_get.await_args.kwargs["params"]
    assert params["observation_start"] == "2000-01-01"
    assert "observation_end" in params


@pytest.mark.asyncio
async def test_fred_source_contains_provenance_not_api_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "secret-test-key")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _FakeResponse(_PAYLOAD)
        sources = await fetch_fred_stats("Graph United States CPI")

    assert len(sources) == 1
    assert sources[0].provider == "Federal Reserve Bank of St. Louis (FRED)"
    assert "CPIAUCSL" in sources[0].snippet
    assert "secret-test-key" not in sources[0].url
    assert "secret-test-key" not in sources[0].snippet


@pytest.mark.asyncio
async def test_live_data_maps_fred_match_to_chart_evidence(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    with (
        patch("app.orchestration.live_data._find_fred_series", new_callable=AsyncMock) as fred,
        patch("app.orchestration.live_data._find_best_series", new_callable=AsyncMock) as dbnomics,
    ):
        from app.orchestration.fred import FredSeriesMatch

        fred.return_value = FredSeriesMatch(
            series_id="UNRATE",
            series_name="US Unemployment Rate",
            points=[("2024-01-01", 3.7), ("2024-02-01", 3.9), ("2024-03-01", 3.8)],
            unit="%",
            frequency="monthly",
            url="https://fred.stlouisfed.org/series/UNRATE",
        )
        # A concurrent DBnomics result must not be mixed into FRED evidence.
        dbnomics.return_value = object()
        result = await fetch_live_data("Show a graph of US unemployment")

    assert len(result.sources) == 1
    assert result.evidence.subject == "US Unemployment Rate"
    assert [point.value for point in result.evidence.observations] == [3.7, 3.9, 3.8]
    assert result.evidence.units == ["%"]


@pytest.mark.asyncio
async def test_fred_failure_is_fail_soft(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=TimeoutError):
        assert await _find_fred_series("Show US GDP") is None
