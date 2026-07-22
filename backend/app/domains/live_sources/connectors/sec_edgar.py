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

import re
from datetime import datetime, timezone

import httpx

from app.domains.live_sources.connectors.base import LiveSourceConnector
from app.domains.live_sources.schemas import LiveDataIntent, NormalizedResponse

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Module-level cache — company_tickers.json is a static reference file, not
# per-query data; re-fetching it on every query would be pure waste. Refreshed
# once per process lifetime, which is fine for a list that changes rarely.
_ticker_cache: dict[str, dict] | None = None

# A candidate must be at least this much shorter than the runner-up
# (top_length / runner_up_length) to be trusted as an unambiguous match —
# see _resolve_unambiguous_match()'s docstring for the real-data
# calibration behind this number.
_AMBIGUITY_MARGIN_RATIO = 0.75


def _normalize(name: str) -> str:
    """Strips everything but letters/digits before comparing names — SEC's
    own titles carry no punctuation or internal spacing consistency (e.g.
    "JPMORGAN CHASE & CO" for what a user would naturally type as "J.P.
    Morgan"), so a plain lowercase substring check misses real matches.
    Confirmed live: without this, "J.P. Morgan" resolved to nothing."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _dedupe_candidates_by_cik(
    ticker_cache: dict, predicate,
) -> list[tuple[str, str, str]]:
    """Returns (normalized_title, title, cik) triples, one per distinct
    CIK, sorted shortest-normalized-title first. company_tickers.json
    lists the same company once per ticker/share class (e.g. common stock
    vs. a preferred series), so the same CIK can appear a dozen times —
    without deduping by CIK, that alone would look like "multiple
    companies matched" and trip the ambiguity guard below for a query that
    isn't actually ambiguous at all (confirmed live: "J.P. Morgan"
    normalizes to a prefix of "JPMORGAN CHASE & CO", which appears 9 times
    in the raw file under 9 different tickers, all the same company)."""
    seen_ciks: set[str] = set()
    candidates: list[tuple[str, str, str]] = []
    for entry in ticker_cache.values():
        cik = str(entry["cik_str"])
        if cik in seen_ciks:
            continue
        normalized_title = _normalize(entry["title"])
        if predicate(normalized_title):
            seen_ciks.add(cik)
            candidates.append((normalized_title, entry["title"], cik))
    candidates.sort(key=lambda c: len(c[0]))
    return candidates


def _resolve_unambiguous_match(
    candidates: list[tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    """Picks the single best candidate, refusing to guess when the result
    would be an arbitrary pick among genuinely competing companies.

    The original implementation returned whichever substring match the
    ticker file happened to list first — for a generic/partial name that
    is silently wrong, not silently absent. Verified live against SEC's
    real company_tickers.json:
      - "West" prefix-matches 41 distinct real companies; "first in file"
        was WESTLAKE CORP, an arbitrary pick with no basis for confidence.
      - "General" prefix-matches "General Motors Co" and "GENERAL MILLS
        INC" at the exact same normalized length (15 chars) — a genuine
        tie with no principled way to prefer one over the other.
      - "American" and "Meta" similarly resolve to an obscure company
        (American Well Corp, MetaVia Inc.) that is almost certainly not
        what the user meant, simply because it has a marginally shorter
        title than the actual intended company.
    For an accounting/finance assistant, a confident wrong answer
    attributed to real filed data is worse than asking for clarification.

    Resolution rule, calibrated against the live data above:
      - Zero candidates -> no match (caller raises "no company found").
      - Exactly one candidate -> always safe to return, regardless of how
        loose the match is (e.g. "Exxon" -> "ExxonMobil Holdings Corp" is
        the ONLY company matching at all, so there is nothing to confuse
        it with, even though the title is much longer than the query).
      - Multiple candidates -> only auto-resolve if the shortest (closest)
        match is meaningfully tighter than the runner-up: normalized
        length ratio top/runner-up <= 0.75, i.e. the runner-up is at
        least ~33% longer. "Intel" (9 vs. 15 chars, ratio 0.60) clears
        this and resolves to INTEL CORP; "Meta" (10 vs. 11, ratio 0.91)
        and "American" (16 vs. 17, ratio 0.94) do not, since the top
        candidate isn't decisively closer than a real competing company.
        A tie (ratio 1.0, e.g. "General") is rejected by the same check.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    top, runner_up = candidates[0], candidates[1]
    if len(top[0]) / len(runner_up[0]) <= _AMBIGUITY_MARGIN_RATIO:
        return top
    return None


import asyncio

class SECEdgarConnector(LiveSourceConnector):
    provider_key = "sec_edgar"

    def __init__(self, base_url: str, user_agent: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        # SEC EDGAR limits to 10 req/sec globally per IP. Guard concurrency at 5.
        self._semaphore = asyncio.Semaphore(5)

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

        # Tier 1: exact ticker symbol match — unambiguous by construction,
        # a ticker identifies exactly one company/share class.
        query_lower = company_query.strip().lower()
        for entry in _ticker_cache.values():
            if entry["ticker"].lower() == query_lower:
                return str(entry["cik_str"]).zfill(10), entry["title"]

        # Tier 2: normalized name match. Prefer a prefix match (the query is
        # the start of the official title, e.g. "Apple" -> "Apple Inc.");
        # only fall back to a bare substring search if nothing starts with
        # the query at all (e.g. the classifier extracted a middle/partial
        # fragment) — a substring-anywhere search run first would only add
        # more competing candidates, making ambiguity worse, not better.
        query_normalized = _normalize(company_query)
        candidates = _dedupe_candidates_by_cik(
            _ticker_cache, lambda title_normalized: title_normalized.startswith(query_normalized)
        )
        if not candidates:
            candidates = _dedupe_candidates_by_cik(
                _ticker_cache, lambda title_normalized: query_normalized in title_normalized
            )

        match = _resolve_unambiguous_match(candidates)
        if match is not None:
            _, title, cik = match
            return cik.zfill(10), title

        if len(candidates) > 1:
            sample = ", ".join(title for _, title, _ in candidates[:5])
            raise ValueError(
                f"SEC EDGAR: {company_query!r} matches {len(candidates)} different companies "
                f"(e.g. {sample}) — ask about a more specific company name"
            )
        raise ValueError(f"SEC EDGAR: no company found matching {company_query!r}")

    async def fetch(self, intent: LiveDataIntent, *, timeout: float, client: httpx.AsyncClient | None = None) -> NormalizedResponse:
        if not intent.company_query:
            raise ValueError("SEC EDGAR connector requires LiveDataIntent.company_query")

        async with self._semaphore:
            if client is not None:
                cik, company_name = await self._resolve_cik(client, intent.company_query)
                facts_response = await client.get(
                    f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json", headers=self._headers()
                )
                facts_response.raise_for_status()
                body = facts_response.json()
            else:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    cik, company_name = await self._resolve_cik(c, intent.company_query)
                    facts_response = await c.get(
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
