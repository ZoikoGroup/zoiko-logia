from unittest.mock import AsyncMock

import pytest

from app.orchestration import dbnomics
from app.orchestration.websearch import build_web_grounded_prompt


@pytest.mark.asyncio
async def test_comparison_retrieves_both_country_series(monkeypatch):
    async def observations(_client, _indicator, iso3):
        return [("2024", 2.0), ("2025", 2.2 if iso3 == "DEU" else 0.9)]

    monkeypatch.setattr(dbnomics, "_fetch_world_bank", observations)
    sources = await dbnomics.fetch_stats(
        "Compare Germany and France inflation over the most recent five years"
    )

    assert [source.title for source in sources] == [
        "Inflation, consumer prices (annual %) — Germany",
        "Inflation, consumer prices (annual %) — France",
    ]
    assert all("Latest available year: 2025" in source.snippet for source in sources)


@pytest.mark.asyncio
async def test_missing_comparison_series_does_not_return_partial_data(monkeypatch):
    async def observations(_client, _indicator, iso3):
        return [("2025", 2.2)] if iso3 == "DEU" else []

    monkeypatch.setattr(dbnomics, "_fetch_world_bank", observations)
    monkeypatch.setattr(dbnomics, "_fetch_wdi", AsyncMock(return_value=None))

    assert await dbnomics.fetch_stats("Compare Germany and France inflation") == []


def test_missing_statistics_do_not_request_an_illustrative_chart():
    prompt = build_web_grounded_prompt(
        "Chart Germany and France inflation", []
    )
    assert "verified data could not be retrieved" in prompt
    assert "do not emit a chart block" in prompt
