"""
Bank of England Interactive Statistical Database (IADB) connector —
https://www.bankofengland.co.uk/boeapps/database. Fully keyless. Fills the
one gap World Bank never covered: the UK's Bank Rate (repo-rate
equivalent) — World Bank has no UK repo-rate series at all.

Unlike every other connector here, this endpoint returns CSV, not JSON, and
blocks requests with no browser-like User-Agent header (confirmed: the
default httpx/generic-bot UA gets a 403; a normal browser UA string does
not) — this is the one connector that needs both a CSV parser and an
explicit User-Agent.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_BANK_RATE_SERIES_CODE = "IUDBEDR"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class BankOfEnglandConnector(LiveSourceConnector):
    provider_key = "bank_of_england"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        url = f"{self.base_url}/_iadb-fromshowcolumns.asp"
        params = {
            "csv.x": "yes",
            "SeriesCodes": _BANK_RATE_SERIES_CODE,
            "UsingCodes": "Y",
            "CSVF": "TT",  # tabular with titles -> a header row, so the value column is found by name
            "Datefrom": "01/Jan/2020",
            "Dateto": "now",
        }

        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            text = response.text.replace("\r\n", "\n")  # BoE serves CRLF line endings

        # Response has two CSV blocks separated by a blank line: a 2-row
        # "SERIES,DESCRIPTION" metadata block, then "DATE,<series_code>" data
        # rows. Only the second block is parsed.
        blocks = text.strip().split("\n\n")
        if len(blocks) < 2:
            raise ValueError("Bank of England API returned an unexpected CSV shape (no data block found)")

        rows = list(csv.DictReader(io.StringIO(blocks[1])))
        if not rows:
            raise ValueError(f"Bank of England API returned no observations for {_BANK_RATE_SERIES_CODE}")

        latest = rows[-1]
        value = latest.get(_BANK_RATE_SERIES_CODE)
        date_str = latest.get("DATE")
        if value is None or date_str is None:
            raise ValueError(f"Bank of England API row missing expected columns: {latest}")

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=float(value),
            unit="%",
            observation_period=date_str,
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=url,
            citation_title=f"Bank of England — {intent.indicator_label}, {date_str}",
        )
