"""
SEC EDGAR company-facts retrieval for Ask Kriton™.

EDGAR (https://data.sec.gov) is the SEC's own filing system, served as a free,
keyless JSON API. When a question asks for a US-listed company's reported
figure (revenue, net income, total assets, EPS…), this resolves the company to
its CIK, pulls the exact value the company itself filed in its 10-K, and
returns it as a WebSource — the SAME shape SearXNG results use — so it merges
straight into the existing grounded answer pipeline (grounding context +
[REF-N] source panel) with no other change.

Two design choices, both for data-honesty (this is a finance bot):
  - Figures come from the XBRL facts the registrant filed, not from a summary
    or a third party, and the snippet names the exact concept, fiscal period,
    form type and accession number the number came from. A reader can open the
    linked filing index and find the same figure.
  - It answers ONLY when it can resolve both a company AND a known concept.
    Anything ambiguous returns [] and the bot falls back to its normal
    web-grounded answer rather than guessing which company was meant.

Requires SEC_USER_AGENT to be set (e.g. "ZoikoLogia Kriton ops@example.com").
The SEC's access policy requires a User-Agent identifying the requester and
blocks traffic without one, so with it unset this connector stays silent
rather than risking an IP-level ban on a shared egress address.

Fails soft on any non-company question, unresolved company, or network/parse
error → returns [].
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional

import httpx

from app.orchestration.websearch import WebSource

# ── Concept registry ──────────────────────────────────────────────────────────
# Question wording -> (display label, candidate us-gaap tags in priority order).
# Several tags per concept because filers legitimately differ: post-ASC 606
# registrants report revenue under RevenueFromContractWithCustomer…, older or
# non-606 filings under Revenues/SalesRevenueNet. First tag with data wins.
_CONCEPTS: list[tuple[re.Pattern, str, tuple[str, ...]]] = [
    (
        re.compile(r"\b(gross\s+profit|gross\s+margin)\b", re.I),
        "Gross profit",
        ("GrossProfit",),
    ),
    (
        re.compile(r"\b(operating\s+(income|profit|earnings))\b", re.I),
        "Operating income",
        ("OperatingIncomeLoss",),
    ),
    (
        re.compile(r"\b(net\s+(income|profit|earnings)|bottom\s+line)\b", re.I),
        "Net income",
        ("NetIncomeLoss",),
    ),
    (
        re.compile(r"\b(revenue|revenues|turnover|top\s+line|net\s+sales|total\s+sales)\b", re.I),
        "Revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
    ),
    (
        re.compile(r"\b(total\s+assets|balance\s+sheet\s+size)\b|\bassets\b", re.I),
        "Total assets",
        ("Assets",),
    ),
    (
        re.compile(r"\btotal\s+liabilities\b|\bliabilities\b", re.I),
        "Total liabilities",
        ("Liabilities",),
    ),
    (
        re.compile(r"\b(shareholders?|stockholders?)'?\s+equity\b|\bbook\s+value\b", re.I),
        "Stockholders' equity",
        ("StockholdersEquity",),
    ),
    (
        re.compile(r"\b(cash\s+and\s+cash\s+equivalents|cash\s+position|cash\s+balance)\b", re.I),
        "Cash and cash equivalents",
        ("CashAndCashEquivalentsAtCarryingValue",),
    ),
    (
        re.compile(r"\b(eps|earnings\s+per\s+share)\b", re.I),
        "Diluted EPS",
        ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    ),
    (
        re.compile(r"\b(r&d|research\s+and\s+development)\b", re.I),
        "Research and development expense",
        ("ResearchAndDevelopmentExpense",),
    ),
]

# Cap the fan-out: a question naming several metrics still costs a bounded
# number of EDGAR calls, and more than three citations from one source stops
# being useful provenance and starts being noise.
_MAX_CONCEPTS = 3

# Corporate-form suffixes stripped when matching a company name in prose, so
# "Apple" matches the registrant titled "Apple Inc.".
_NAME_SUFFIXES = re.compile(
    r"\b(inc|inc\.|incorporated|corp|corp\.|corporation|co|co\.|company|ltd|ltd\.|"
    r"limited|plc|llc|lp|holdings?|group|trust|the)\b|/[a-z]{2}/|,",
    re.I,
)

# Uppercase tokens that look like tickers but are ordinary words or jargon in a
# finance question. Ticker matching is only a fallback behind name matching,
# but these would fire often enough to matter.
_TICKER_STOPWORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT",
    "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "UK", "WE", "ALL",
    "AND", "ANY", "ARE", "CAN", "FOR", "HAS", "HOW", "NEW", "NOT", "NOW", "ONE",
    "OUT", "THE", "WAS", "WHO", "WHY", "YOU", "CEO", "CFO", "EPS", "GDP", "SEC",
    "USA", "VAT", "GST", "TAX", "ROI", "ROE", "IPO", "ETF", "GAAP", "IFRS",
    "EBIT", "FY", "Q1", "Q2", "Q3", "Q4", "K", "Q",
}

# The registrant index is ~1 MB and changes rarely; refetching it per question
# would dominate this connector's latency and its share of the SEC rate limit.
_TICKERS_TTL_SECONDS = 24 * 60 * 60
_tickers_cache: Optional[list[dict]] = None
_tickers_fetched_at: float = 0.0
_tickers_lock = asyncio.Lock()


def _data_base() -> str:
    return os.getenv("SEC_EDGAR_API_BASE_URL", "https://data.sec.gov").rstrip("/")


def _www_base() -> str:
    return os.getenv("SEC_EDGAR_WWW_BASE_URL", "https://www.sec.gov").rstrip("/")


# Substrings that mark a User-Agent as copied-but-not-filled-in. A fake contact
# is worse than none: the SEC uses it to reach an operator before blocking, so
# an unreachable address turns a warning into a silent IP-level block on
# whatever egress address the deployment shares.
_PLACEHOLDER_AGENT_MARKERS = ("example.com", "example.org", "your-email", "<", ">")


def _user_agent() -> str:
    """SEC requires a descriptive User-Agent with real contact details. Returns
    "" — meaning "not configured", and the connector declines to call EDGAR at
    all — when unset or still holding a .env.example placeholder."""
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    lowered = agent.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_AGENT_MARKERS):
        return ""
    # A bare address with no contactable mailbox is equally unusable.
    if "@" not in agent:
        return ""
    return agent


def normalise_company_name(title: str) -> str:
    """Registrant title -> bare name for prose matching ("Apple Inc." -> "apple")."""
    stripped = _NAME_SUFFIXES.sub(" ", title.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", stripped).strip()


def pick_concepts(query: str) -> list[tuple[str, tuple[str, ...]]]:
    """Concepts the question asks for, in registry order, capped at _MAX_CONCEPTS.

    Registry order is deliberate: the specific patterns ("gross profit",
    "operating income") sit above the generic ones ("revenue", "assets") so a
    question about gross profit does not also drag in every revenue tag.
    """
    found: list[tuple[str, tuple[str, ...]]] = []
    for pattern, label, tags in _CONCEPTS:
        if pattern.search(query):
            found.append((label, tags))
        if len(found) >= _MAX_CONCEPTS:
            break
    return found


def find_year(query: str) -> Optional[int]:
    """An explicit fiscal year in the question, if any ("Apple revenue 2023")."""
    match = re.search(r"\b(19|20)\d{2}\b", query)
    if not match:
        return None
    year = int(match.group(0))
    return year if 1993 <= year <= 2100 else None


def resolve_company(query: str, registrants: list[dict]) -> Optional[dict]:
    """Resolve the company a question is about to its registrant entry.

    Name match first — it is how people actually write ("Apple's revenue") and
    it cannot collide with ordinary words the way a bare ticker can. The
    longest matching name wins, so "Ford Motor" beats a registrant merely named
    "Ford". Ticker matching is the fallback, guarded by _TICKER_STOPWORDS and
    requiring the token to be uppercase in the original text, so "IT spending"
    does not resolve to the ticker IT.
    """
    best: Optional[dict] = None
    best_len = 0
    best_title_score = 0
    for entry in registrants:
        name = normalise_company_name(str(entry.get("title", "")))
        # Names shorter than this collide with ordinary prose far too often
        # ("Gap", "Box"); those stay reachable via their ticker instead.
        if len(name) < 4:
            continue
        match = re.search(
            rf"(?<![A-Za-z0-9]){re.escape(name)}(?:['’]s)?(?![A-Za-z0-9])",
            query,
            re.I,
        )
        if match is None:
            continue
        # A bare lowercase single word is prose, not a company. Registrants
        # named after ordinary words ("Sound Group", "Target Group") otherwise
        # hijack generic questions — "explain sound revenue recognition" and
        # "set a target revenue" both resolved to real filers before this
        # guard, attaching that company's figures as provenance for a question
        # that was never about them. Any ONE of these marks a real reference:
        matched = match.group(0)
        capitalised = matched[:1].isupper()
        possessive = matched.endswith(("'s", "’s"))
        multi_word = " " in name
        if not (capitalised or possessive or multi_word):
            continue
        # Distinct registrants can share a normalised name ("Target Group Inc."
        # and "TARGET CORP" both reduce to "target"), so length alone leaves
        # the winner down to list order. Break the tie on how much of the full
        # filed title the question actually contains, which is what tells
        # "Target Corp revenue" apart from a same-named shell.
        full_title = re.sub(r"[^a-z0-9 ]+", " ", str(entry.get("title", "")).lower())
        full_title = re.sub(r"\s+", " ", full_title).strip()
        title_score = len(full_title) if full_title and full_title in query.lower() else 0
        if (len(name), title_score) > (best_len, best_title_score):
            best, best_len, best_title_score = entry, len(name), title_score
    if best is not None:
        return best

    uppercase_tokens = {
        tok for tok in re.findall(r"\b[A-Z][A-Z0-9.\-]{1,4}\b", query)
        if tok not in _TICKER_STOPWORDS
    }
    if not uppercase_tokens:
        return None
    for entry in registrants:
        if str(entry.get("ticker", "")).upper() in uppercase_tokens:
            return entry
    return None


def latest_annual_fact(units: dict, year: Optional[int] = None) -> Optional[dict]:
    """Pick the annual fact to quote from a companyconcept `units` payload.

    Annual reports only (10-K and its amendments): a 10-Q figure quoted as "the"
    revenue would be a quarter presented as a year. Duration facts are further
    required to span most of a year, since 10-K payloads also carry the
    embedded quarterly periods.
    """
    for unit_key in ("USD", "USD/shares"):
        facts = units.get(unit_key)
        if not facts:
            continue

        eligible = []
        for fact in facts:
            form = str(fact.get("form", ""))
            if not form.startswith("10-K"):
                continue
            end = str(fact.get("end", ""))
            if not end:
                continue
            start = fact.get("start")
            if start:
                # Duration fact — keep only full-year periods, not the quarters
                # a 10-K also reports.
                try:
                    start_y, start_m, start_d = (int(p) for p in str(start).split("-"))
                    end_y, end_m, end_d = (int(p) for p in end.split("-"))
                    span_days = (end_y - start_y) * 365 + (end_m - start_m) * 30 + (end_d - start_d)
                except ValueError:
                    continue
                if span_days < 300:
                    continue
            if not isinstance(fact.get("val"), (int, float)):
                continue
            eligible.append({**fact, "unit": unit_key})

        if not eligible:
            continue
        if year is not None:
            matching = [
                f for f in eligible
                if f.get("fy") == year or str(f.get("end", "")).startswith(str(year))
            ]
            if matching:
                return max(matching, key=lambda f: str(f.get("end", "")))
        return max(eligible, key=lambda f: str(f.get("end", "")))
    return None


def format_value(value: float, unit: str) -> str:
    """Exact figure first, with a scaled reading alongside for large amounts —
    "391,035,000,000" is precise but "391.04 billion" is what a reader checks."""
    if unit == "USD/shares":
        return f"${value:,.2f} per share"
    exact = f"${value:,.0f}"
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{exact} (${value / 1e9:,.2f} billion)"
    if magnitude >= 1e6:
        return f"{exact} (${value / 1e6:,.2f} million)"
    return exact


def filing_index_url(cik: int, accession: str) -> str:
    """Public index page for the filing a fact came from, so the citation lands
    on the document itself rather than on a JSON endpoint."""
    compact = accession.replace("-", "")
    return f"{_www_base()}/Archives/edgar/data/{cik}/{compact}/{accession}-index.htm"


async def _load_registrants(client: httpx.AsyncClient) -> list[dict]:
    """Ticker/CIK index, cached in-process for _TICKERS_TTL_SECONDS."""
    global _tickers_cache, _tickers_fetched_at

    now = time.monotonic()
    if _tickers_cache is not None and (now - _tickers_fetched_at) < _TICKERS_TTL_SECONDS:
        return _tickers_cache

    async with _tickers_lock:
        # Another request may have populated the cache while we waited.
        now = time.monotonic()
        if _tickers_cache is not None and (now - _tickers_fetched_at) < _TICKERS_TTL_SECONDS:
            return _tickers_cache

        resp = await client.get(f"{_www_base()}/files/company_tickers.json")
        resp.raise_for_status()
        payload = resp.json()
        # Keyed by stringified row index ("0", "1", …), not a list.
        registrants = [row for row in payload.values() if isinstance(row, dict)]
        _tickers_cache = registrants
        _tickers_fetched_at = time.monotonic()
        return registrants


async def _fetch_concept(
    client: httpx.AsyncClient, cik: int, label: str, tags: tuple[str, ...], year: Optional[int]
) -> Optional[tuple[str, dict]]:
    """First candidate tag that yields a usable annual fact, or None."""
    for tag in tags:
        try:
            resp = await client.get(
                f"{_data_base()}/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
            )
            if resp.status_code == 404:
                # Filer does not report under this tag — try the next candidate.
                continue
            resp.raise_for_status()
            fact = latest_annual_fact(resp.json().get("units", {}) or {}, year)
        except Exception:
            continue
        if fact is not None:
            return label, fact
    return None


async def fetch_sec_facts(query: str) -> list[WebSource]:
    """Return one WebSource per resolved concept with the company's own filed
    figure, when the question names a US registrant and a known concept; else []."""
    agent = _user_agent()
    if not agent:
        return []

    concepts = pick_concepts(query)
    if not concepts:
        return []

    year = find_year(query)
    headers = {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            registrants = await _load_registrants(client)
            company = resolve_company(query, registrants)
            if company is None:
                return []

            cik = int(company["cik_str"])
            results = await asyncio.gather(
                *(_fetch_concept(client, cik, label, tags, year) for label, tags in concepts),
                return_exceptions=True,
            )
    except Exception:
        return []

    entity = str(company.get("title", "")).strip()
    ticker = str(company.get("ticker", "")).strip()
    sources: list[WebSource] = []
    for result in results:
        if not isinstance(result, tuple):
            continue
        label, fact = result
        value = format_value(float(fact["val"]), str(fact.get("unit", "USD")))
        period_end = str(fact.get("end", ""))
        fiscal_year = fact.get("fy")
        form = str(fact.get("form", "10-K"))
        accession = str(fact.get("accn", ""))
        snippet = (
            f"As filed with the SEC by {entity} ({ticker}). "
            f"{label} for the period ending {period_end}"
            f"{f' (FY{fiscal_year})' if fiscal_year else ''}: {value}. "
            f"Source: {form} filing, accession {accession}, "
            f"reported under US-GAAP XBRL taxonomy."
        )
        sources.append(
            WebSource(
                title=f"SEC EDGAR — {entity} {label} ({period_end})"[:200],
                url=filing_index_url(cik, accession) if accession else f"{_www_base()}/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
                snippet=snippet,
            )
        )
    return sources
