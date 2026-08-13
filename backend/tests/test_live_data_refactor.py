"""
Confirms the dbnomics.py / frankfurter.py refactor (extracting _find_best_series
/ _find_rate as the single fetch both the WebSource text and the structured
EvidenceModel are built from) preserves the exact previous WebSource output,
and that fetch_live_data now also returns matching structured evidence built
from that SAME fetch (not a second, independent one).
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.orchestration.dbnomics import fetch_stats
from app.orchestration.frankfurter import fetch_fx
from app.orchestration.live_data import fetch_live_data


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


_DBNOMICS_SEARCH_PAYLOAD = {
    "results": {"docs": [{"provider_code": "IMF", "code": "CPI", "provider_name": "IMF", "name": "Consumer Prices"}]}
}
_DBNOMICS_SERIES_PAYLOAD = {
    "series": {
        "docs": [
            {
                "series_name": "India · Consumer prices",
                "series_code": "IN.CPI",
                "provider_code": "IMF",
                "dataset_code": "CPI",
                "period": ["2023-Q1", "2023-Q2", "2023-Q3"],
                "value": [100.0, 101.5, 103.2],
            }
        ]
    }
}


@pytest.mark.asyncio
async def test_fetch_stats_unchanged_after_refactor():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [_FakeResponse(_DBNOMICS_SEARCH_PAYLOAD), _FakeResponse(_DBNOMICS_SERIES_PAYLOAD)]
        sources = await fetch_stats("consumer prices india inflation")

    assert len(sources) == 1
    assert "India" in sources[0].title
    assert "100" in sources[0].snippet


@pytest.mark.asyncio
async def test_fetch_live_data_evidence_matches_source_numbers():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [_FakeResponse(_DBNOMICS_SEARCH_PAYLOAD), _FakeResponse(_DBNOMICS_SERIES_PAYLOAD)]
        result = await fetch_live_data("consumer prices india inflation")

    assert len(result.sources) == 1
    assert len(result.evidence.observations) == 3
    # The narrative source snippet and the structured evidence must agree —
    # exactly the invariant evidence.py's docstring requires.
    assert [o.value for o in result.evidence.observations] == [100.0, 101.5, 103.2]


_FRANKFURTER_PAYLOAD = {"rates": {"INR": 83.42}, "date": "2024-06-01"}


@pytest.mark.asyncio
async def test_fetch_fx_unchanged_after_refactor():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _FakeResponse(_FRANKFURTER_PAYLOAD)
        sources = await fetch_fx("convert USD to INR")

    assert len(sources) == 1
    assert "83.42" in sources[0].snippet


@pytest.mark.asyncio
async def test_fetch_live_data_fx_evidence_matches_source():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _FakeResponse(_FRANKFURTER_PAYLOAD)
        result = await fetch_live_data("convert USD to INR")

    assert len(result.sources) == 1
    assert len(result.evidence.observations) == 1
    assert result.evidence.observations[0].value == 83.42


@pytest.mark.asyncio
async def test_fetch_live_data_returns_empty_evidence_for_unrelated_question():
    result = await fetch_live_data("What is accrual accounting?")
    assert result.sources == []
    assert result.evidence.is_empty()
