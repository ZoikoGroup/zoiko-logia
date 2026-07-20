"""
SEC EDGAR connector — https://data.sec.gov. Fully keyless, but SEC blocks
requests with no descriptive User-Agent (confirmed live this session — a
generic/missing one is rejected). Company name/ticker is resolved to a CIK
via https://www.sec.gov/files/company_tickers.json, a static reference file
(~10,400 companies) cached in-process after the first fetch rather than
re-downloaded every query.

indicator_code on the intent is a us-gaap XBRL concept name (e.g.
"Assets", "Revenues", "NetIncomeLoss" — see live_sources/classifier.py's
_FINANCIAL_CONCEPT_KEYWORDS). Confirmed live this session: Apple's
"Assets" concept resolves correctly to real filed figures.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Module-level cache — company_tickers.json is a static reference file, not
# per-query data; re-fetching it on every query would be pure waste. Refreshed
# once per process lifetime, which is fine for a list that changes rarely.
_ticker_cache: dict[str, dict] | None = None


class SECEdgarConnector(LiveSourceConnector):
    provider_key = "sec_edgar"

    def __init__(self, base_url: str, user_agent: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent

    def _headers(self) -> dict:
        if not self.user_agent:
            raise ValueError(
                "SEC_EDGAR_USER_AGENT is not configured — SEC requires a real contact "
                "identifier (e.g. 'YourApp your-email@example.com'); set it in backend/.env"
            )
        return {"User-Agent": self.user_agent}

    async def _resolve_cik(self, client: httpx.AsyncClient, company_query: str) -> tuple[str, str]:
        global _ticker_cache
        if _ticker_cache is None:
            response = await client.get(_TICKERS_URL, headers=self._headers())
            response.raise_for_status()
            _ticker_cache = response.json()

        query_lower = company_query.strip().lower()
        for entry in _ticker_cache.values():
            if entry["ticker"].lower() == query_lower:
                return str(entry["cik_str"]).zfill(10), entry["title"]
        for entry in _ticker_cache.values():
            if query_lower in entry["title"].lower():
                return str(entry["cik_str"]).zfill(10), entry["title"]

        raise ValueError(f"SEC EDGAR: no company found matching {company_query!r}")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float) -> NormalizedResponse:
        if not intent.company_query:
            raise ValueError("SEC EDGAR connector requires LiveDataIntent.company_query")

        async with httpx.AsyncClient(timeout=timeout) as client:
            cik, company_name = await self._resolve_cik(client, intent.company_query)

            facts_response = await client.get(
                f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json", headers=self._headers()
            )
            facts_response.raise_for_status()
            body = facts_response.json()

        concept = (body.get("facts", {}).get("us-gaap", {}) or {}).get(intent.indicator_code)
        if concept is None:
            raise ValueError(f"SEC EDGAR: {company_name} has no reported concept {intent.indicator_code!r}")

        usd_entries = (concept.get("units", {}) or {}).get("USD") or []
        if not usd_entries:
            raise ValueError(f"SEC EDGAR: {company_name}'s {intent.indicator_code} has no USD-denominated entries")

        latest = max(usd_entries, key=lambda entry: entry["end"])

        return NormalizedResponse(
            provider_key=self.provider_key,
            indicator_code=intent.indicator_code,
            indicator_label=intent.indicator_label,
            country_code=intent.country_code,
            country_label=intent.country_label,
            value=latest["val"],
            unit="USD",
            observation_period=f"{latest.get('end')} ({latest.get('form', 'unknown form')})",
            as_of=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            citation_title=f"SEC EDGAR — {company_name}, {intent.indicator_label}, {latest.get('end')} ({latest.get('form')})",
            company_query=intent.company_query,
        )
