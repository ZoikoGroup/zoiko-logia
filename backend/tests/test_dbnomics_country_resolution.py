from unittest.mock import AsyncMock, patch

import pytest

from app.orchestration.dbnomics import _find_series_for_phrase, _find_two_series
from app.orchestration.intent_classifier import classify_intent, CORRELATION


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _country_payload(country: str):
    return {
        "series": {"docs": [{
            "series_name": f"Monthly · {country} · All items · Index",
            "series_code": f"M.{country[:2].upper()}.IX",
            "period": ["2025-01", "2025-02", "2025-03", "2025-04"],
            "value": [100.0, 101.0, 102.0, 103.0],
        }]}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase,country", [
    ("US inflation", "United States"),
    ("France inflation", "France"),
    ("Germany inflation", "Germany"),
    ("India inflation", "India"),
    ("UK inflation", "United Kingdom"),
    ("Canada inflation", "Canada"),
])
async def test_country_inflation_uses_targeted_imf_cpi_series(phrase, country):
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        get.return_value = _Response(_country_payload(country))
        match = await _find_series_for_phrase(phrase)

    assert match is not None
    assert country in match.series_name
    assert match.dataset_name == "Consumer Price Index (CPI)"
    assert f".{ {'United States': 'US', 'United Kingdom': 'GB', 'India': 'IN', 'Germany': 'DE', 'France': 'FR', 'Canada': 'CA'}[country] }." in get.await_args.args[0]
    assert get.await_args.kwargs["params"] == {"observations": "1"}


@pytest.mark.asyncio
async def test_country_inflation_never_falls_back_to_unrelated_generic_search():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        get.side_effect = RuntimeError("targeted CPI temporarily unavailable")
        assert await _find_series_for_phrase("Canada inflation") is None
    assert get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "Compare UK and US inflation using a grouped bar chart.",
    "Compare India and UK CPI using a grouped bar chart.",
    "Compare Germany and France inflation using a scatter plot.",
])
async def test_cross_country_comparisons_resolve_two_aligned_cpi_series(query):
    async def fake_get(_self, url, *, params=None, **_kwargs):
        code = str(url).rsplit("/", 1)[-1].split(".")[1]
        country = {
            "US": "United States", "GB": "United Kingdom", "IN": "India",
            "DE": "Germany", "FR": "France", "CA": "Canada",
        }[code]
        return _Response(_country_payload(country))

    with patch("httpx.AsyncClient.get", new=fake_get):
        pair = await _find_two_series(query)

    assert classify_intent(query) == CORRELATION
    assert pair is not None
    assert len(pair[0].points) == len(pair[1].points) == 4
