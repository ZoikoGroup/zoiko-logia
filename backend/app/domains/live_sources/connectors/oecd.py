"""
OECD connector — https://sdmx.oecd.org/public/rest. Fully keyless. Supports
the combined corporate income tax rate (dataflow
OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,1.0) — the one tax-specific figure none of
the other connectors (World Bank/ONS/BoE/FRED) carry, and the most directly
relevant to an accounting/tax assistant.

indicator_code on the intent is "{REF_AREA}:{MEASURE}" (e.g. "GBR:CIT_C") —
see live_sources/classifier.py's _match_oecd_indicator(). REF_AREA is ISO
alpha-3, unlike this codebase's own alpha-2 country codes elsewhere.

Query template confirmed live against three real countries this session:
GBR=25% (2025), USA=25.57% (2025, combined federal+state average), IND=25.17%
(2024) — all matching known real-world corporate tax rates. Leaving the
SECTOR dimension wildcarded (empty) correctly returns exactly one series per
country for the CIT_C ("Combined") measure — no need to pick between
S1/S13/S1311 (Total economy/General government/Central government), unlike
what a naive reading of the dataflow's dimension structure would suggest.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_DATAFLOW = "OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,1.0"


class OECDConnector(LiveSourceConnector):
    provider_key = "oecd"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        ref_area, _, measure = intent.indicator_code.partition(":")
        if not ref_area or not measure:
            raise ValueError(f"OECD connector got a malformed indicator code: {intent.indicator_code!r}")

        # Dimension order: REF_AREA.FREQ.MEASURE.TARGETING.UNIT_MEASURE.
        # SECTOR.RATE_STRUCTURE.TAX_BASE (8 positions, 7 dots) — confirmed
        # via the dataflow's own structure definition this session.
        # TARGETING=ST (Statutory, not small-business-targeted),
        # UNIT_MEASURE=PT_INC_TAX (percentage of taxable income) are fixed;
        # SECTOR is left wildcarded (empty) — confirmed live to resolve to
        # exactly one series for the CIT_C measure; RATE_STRUCTURE/TAX_BASE
        # only ever have one possible value (_Z, "Not applicable").
        data_key = f"{ref_area}.A.{measure}.ST.PT_INC_TAX..._Z._Z"
        url = f"{self.base_url}/data/{_DATAFLOW}/{data_key}"
        params = {"format": "jsondata", "lastNObservations": "1"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            body = response.json()

        try:
            dataset = body["data"]["dataSets"][0]
            series_map = dataset["series"]
            if not series_map:
                raise KeyError("no series in response")
            # Exactly one series expected once SECTOR resolves unambiguously
            # for the CIT_C measure (confirmed live) — take it regardless
            # of its exact key, rather than assuming a specific key string.
            series = next(iter(series_map.values()))
            observations = series["observations"]
            if not observations:
                raise KeyError("no observations in series")
            # lastNObservations=1 means exactly one observation key, but its
            # numeric index isn't guaranteed to be "0" — take whichever key
            # is present rather than assuming.
            obs_index, obs_value = next(iter(observations.items()))
            value = obs_value[0]
            if value is None:
                raise ValueError(f"OECD API has no non-empty value for {intent.indicator_code}")

            structure = body["data"]["structures"][0]
            time_values = structure["dimensions"]["observation"][0]["values"]
            period_label = time_values[int(obs_index)]["id"]
        except (KeyError, IndexError, StopIteration) as exc:
            raise ValueError(f"OECD API returned no observations for {intent.indicator_code}: {exc}") from exc

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=float(value),
            unit="%",
            observation_period=period_label,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://data-explorer.oecd.org/vis?df[id]=DSD_TAX_CIT@DF_CIT&df[ag]=OECD.CTP.TPS",
            citation_title=f"OECD — {intent.country_label}, {intent.indicator_label}, {period_label}",
        )
