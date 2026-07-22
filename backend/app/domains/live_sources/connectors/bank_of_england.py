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
import csv
import io
import random
from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_BANK_RATE_SERIES_CODE = "IUDBEDR"
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class BankOfEnglandConnector(LiveSourceConnector):
    provider_key = "bank_of_england"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        url = f"{self.base_url}/_iadb-fromshowcolumns.asp"
        params = {
            "csv.x": "yes",
            "SeriesCodes": _BANK_RATE_SERIES_CODE,
            "UsingCodes": "Y",
            "CSVF": "TT",  # tabular with titles -> a header row, so the value column is found by name
            "Datefrom": "01/Jan/2020",
            "Dateto": "now",
        }

        user_agent = random.choice(_USER_AGENTS)
        headers = {"User-Agent": user_agent}
        if client is not None:
            response = await client.get(url, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as c:
                response = await c.get(url, params=params)
        response.raise_for_status()
        text = response.text.replace("\r\n", "\n")  # BoE serves CRLF line endings

        # Response has two CSV blocks separated by a blank line: a 2-row
        # "SERIES,DESCRIPTION" metadata block, then "DATE,<series_code>" data
        # rows. Parse the data block robustly.
        blocks = text.strip().split("\n\n")
        data_block = blocks[1] if len(blocks) >= 2 else text.strip()

        rows = list(csv.DictReader(io.StringIO(data_block)))
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
