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

_GENERIC_FILING_REQUEST = re.compile(
    r"\b(?:SEC|EDGAR)\b(?:(?![.;]).){0,80}\bfilings?\b|"
    r"\bfilings?\b(?:(?![.;]).){0,80}\b(?:SEC|EDGAR)\b|"
    r"\b(?:10-K|10-Q|8-K|20-F|6-K)\s+(?:filings?|reports?)\b|"
    r"\b(?:show|list|get|find)\b(?:(?![.;]).){0,60}\b(?:10-K|10-Q|8-K|20-F|6-K)s?\b",
    re.I,
)

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


def latest_annual_fact(
    units: dict, year: Optional[int] = None, forms: tuple[str, ...] = ("10-K",),
    currency: Optional[str] = None,
) -> Optional[dict]:
    """Pick the annual fact to quote from a companyconcept `units` payload.

    Annual reports only (10-K, or a foreign filer's 20-F/40-F, and their
    amendments): a 10-Q figure quoted as "the" revenue would be a quarter
    presented as a year. Duration facts are further required to span most of
    a year, since annual payloads also carry the embedded quarterly periods.
    USD is preferred; a foreign filer reporting only in its home currency
    (TWD, EUR…) is quoted in that currency. `currency` restricts the choice
    to one currency, so a company's figures are never quoted in a mix.
    """
    preferred = [key for key in ("USD", "USD/shares") if key in units]
    candidates = preferred + sorted(key for key in units if key not in preferred)
    if currency:
        candidates = [key for key in candidates if key.split("/")[0] == currency]
    for unit_key in candidates:
        facts = units.get(unit_key)
        if not facts:
            continue

        eligible = []
        for fact in facts:
            form = str(fact.get("form", ""))
            if not form.startswith(forms):
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
    currency, _, per = unit.partition("/")
    sign = "$" if currency == "USD" else f"{currency} "
    if per == "shares":
        return f"{sign}{value:,.2f} per share"
    exact = f"{sign}{value:,.0f}"
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{exact} ({sign}{value / 1e9:,.2f} billion)"
    if magnitude >= 1e6:
        return f"{exact} ({sign}{value / 1e6:,.2f} million)"
    return exact


def filing_index_url(cik: int, accession: str) -> str:
    """Public index page for the filing a fact came from, so the citation lands
    on the document itself rather than on a JSON endpoint."""
    compact = accession.replace("-", "")
    return f"{_www_base()}/Archives/edgar/data/{cik}/{compact}/{accession}-index.htm"


def _requested_forms(query: str) -> set[str]:
    return {form.upper() for form in re.findall(r"\b(10-K|10-Q|8-K|20-F|6-K)\b", query, re.I)}


def _recent_filings_source(query: str, company: dict, submissions: dict) -> WebSource | None:
    """Build one honest source summary from EDGAR's submissions feed."""
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    accessions = recent.get("accessionNumber") or []
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    descriptions = recent.get("primaryDocDescription") or []
    requested = _requested_forms(query)
    rows: list[tuple[str, str, str, str]] = []
    for index, accession in enumerate(accessions):
        form = str(forms[index]) if index < len(forms) else ""
        if requested and form.upper() not in requested:
            continue
        date = str(dates[index]) if index < len(dates) else ""
        description = str(descriptions[index]) if index < len(descriptions) else ""
        rows.append((date, form, str(accession), description))
        if len(rows) >= 8:
            break
    if not rows:
        return None

    cik = int(company["cik_str"])
    entity = str(company.get("title", "")).strip()
    ticker = str(company.get("ticker", "")).strip()
    lines = "; ".join(
        f"{date}: {form}{f' — {description}' if description else ''}"
        for date, form, _, description in rows
    )
    return WebSource(
        title=f"SEC EDGAR — {entity} recent filings"[:200],
        url=filing_index_url(cik, rows[0][2]),
        snippet=(
            f"Recent filings submitted to the SEC by {entity} ({ticker}): {lines}. "
            "Dates and form types come directly from the registrant's EDGAR submissions record."
        ),
        provider="sec_edgar",
        freshness="filing",
    )


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


# Annual reports: US registrants file a 10-K; foreign private issuers a 20-F
# (or a 40-F from Canada).
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")


async def _fetch_concept(
    client: httpx.AsyncClient, cik: int, label: str, tags: tuple[str, ...], year: Optional[int],
    taxonomy: str = "us-gaap", currency: Optional[str] = None,
) -> Optional[tuple[str, dict]]:
    """The newest usable annual fact across the candidate tags, or None.

    Every tag is checked, not just the first with data: filers switch tags
    over time (Alphabet's latest revenue sits under a different tag than its
    older years), so the first match can be years out of date. Ties on period
    end keep tag priority order."""

    async def one(tag: str) -> Optional[dict]:
        try:
            resp = await client.get(
                f"{_data_base()}/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{tag}.json"
            )
            if resp.status_code == 404:
                # Filer does not report under this tag.
                return None
            resp.raise_for_status()
            return latest_annual_fact(resp.json().get("units", {}) or {}, year, _ANNUAL_FORMS, currency)
        except Exception:
            return None

    facts = [fact for fact in await asyncio.gather(*(one(tag) for tag in tags)) if fact is not None]
    if not facts:
        return None
    newest_end = max(str(fact.get("end", "")) for fact in facts)
    return label, next(fact for fact in facts if str(fact.get("end", "")) == newest_end)


def _registrant_by_exact_name(phrase: str, registrants: list[dict]) -> Optional[dict]:
    """The registrant whose name IS this phrase, in full, or None.

    The safe way to resolve a lower-case company name. resolve_company()
    requires a capital letter, a possessive or a multi-word name before it will
    match, because a bare lower-case word inside a sentence is usually prose —
    "set a target revenue" resolving to TARGET CORP is the documented example.
    That guard cannot be relaxed, but it can be sidestepped honestly: when the
    question, stripped of its scaffolding, consists of NOTHING BUT a
    registrant's name, there is no surrounding prose left for the word to be
    part of. "current nike stock price" reduces to "nike"; "set a target
    revenue for next year" reduces to "set target next year", which is no
    company's name and correctly matches nothing.

    Ambiguity returns None rather than a guess: several filers normalise to
    the same short name, and picking among them by list order is how a
    question about one company ends up carrying another's figures.
    """
    wanted = normalise_company_name(phrase)
    if len(wanted) < 4:
        return None
    matches = [
        entry for entry in registrants
        if normalise_company_name(str(entry.get("title", ""))) == wanted
    ]
    return matches[0] if len(matches) == 1 else None


async def ticker_for_company(
    query: str, *, exact_name: str = "",
) -> Optional[tuple[str, str]]:
    """(ticker, filed company name) for a US registrant named in the question.

    Exposes the registry this module already downloads to callers that only
    need the identifier. market_data/identity.py deliberately refuses to guess
    a ticker from a company name and keeps a hand-written table of sixteen
    well-known ones, so "Nike stock price" resolved to nothing and the question
    fell through to a general web search. company_tickers.json lists every US
    registrant — about ten thousand — and resolve_company() above already
    carries the guards that make name matching safe (minimum length, required
    capitalisation, longest-name-wins, tie-break on the full filed title).

    exact_name is the caller's company-name phrase (market data's
    company_name_hint()). When the strict match above finds nothing, a phrase
    that is exactly a registrant's name resolves anyway — see
    _registrant_by_exact_name for why that is safe where relaxing the guard
    is not.

    Returns None when SEC_USER_AGENT is unset: the SEC blocks unidentified
    traffic, and this must stay as silent about that as fetch_sec_facts is.
    The registrant list is cached in-process, so repeat calls cost nothing.
    """
    agent = _user_agent()
    if not agent:
        return None
    headers = {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            registrants = await _load_registrants(client)
    except Exception:
        return None
    entry = resolve_company(query, registrants)
    if entry is None and exact_name:
        entry = _registrant_by_exact_name(exact_name, registrants)
    if entry is None:
        return None
    ticker = str(entry.get("ticker", "")).strip().upper()
    if not ticker:
        return None
    return ticker, str(entry.get("title", "")).strip()


# Headline figures for a fundamentals request from the agent's market-data
# tool, which names a company but not a concept.
_FUNDAMENTAL_LABELS = ("Revenue", "Operating income", "Net income", "Diluted EPS")

# The same headline figures for foreign filers reporting under IFRS in a 20-F
# (Infosys, TSMC…), which have no us-gaap facts at all.
_IFRS_FUNDAMENTALS: list[tuple[str, tuple[str, ...]]] = [
    ("Revenue", ("RevenueFromContractsWithCustomers", "Revenue")),
    ("Operating income", ("ProfitLossFromOperatingActivities",)),
    ("Net income", ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss")),
    ("Diluted EPS", ("DilutedEarningsLossPerShare", "BasicEarningsLossPerShare")),
]


def _registrant_for_company(company: str, registrants: list[dict]) -> Optional[dict]:
    """A company the agent named — ticker ("MSFT"), well-known name ("Google")
    or filed name ("Alphabet") — to its registrant entry, or None."""
    from app.domains.market_data.identity import known_ticker_for_name

    wanted = company.strip()
    ticker = known_ticker_for_name(wanted)[0]
    if not ticker and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,5}", wanted):
        ticker = wanted
    if ticker:
        by_ticker = [entry for entry in registrants if str(entry.get("ticker", "")).upper() == ticker]
        if by_ticker:
            return by_ticker[0]
    return resolve_company(wanted, registrants) or _registrant_by_exact_name(wanted, registrants)


async def fetch_company_fundamentals(company: str, year: Optional[int] = None) -> Optional[WebSource]:
    """One WebSource with a company's own annual-report headline figures
    (revenue, operating income, net income, diluted EPS) — US-GAAP from a 10-K,
    or IFRS from a foreign filer's 20-F — or None when SEC_USER_AGENT is
    unset, the company doesn't file with the SEC, or EDGAR has none of them."""
    agent = _user_agent()
    if not agent:
        return None
    us_gaap = [(label, tags) for _, label, tags in _CONCEPTS if label in _FUNDAMENTAL_LABELS]
    headers = {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            registrants = await _load_registrants(client)
            entry = _registrant_for_company(company, registrants)
            if entry is None:
                return None
            cik = int(entry["cik_str"])
            facts: list[tuple[str, dict]] = []
            taxonomy = "us-gaap"

            async def fetch_all(concepts, currency: Optional[str] = None) -> list[tuple[str, dict]]:
                results = await asyncio.gather(
                    *(_fetch_concept(client, cik, label, tags, year, taxonomy, currency) for label, tags in concepts),
                    return_exceptions=True,
                )
                return [result for result in results if isinstance(result, tuple)]

            # US-GAAP first; IFRS only when there is none, so a US company
            # costs no extra requests against the SEC's rate limit.
            for taxonomy, concepts in (("us-gaap", us_gaap), ("ifrs-full", _IFRS_FUNDAMENTALS)):
                facts = await fetch_all(concepts)
                if facts:
                    break
            # Foreign filers tag some lines in USD (a convenience translation)
            # and the rest in their home currency. Quote everything in the
            # currency revenue is reported in, never a mix.
            currencies = {str(fact.get("unit", "USD")).split("/")[0] for _, fact in facts}
            if len(currencies) > 1:
                revenue = next((fact for label, fact in facts if label == "Revenue"), facts[0][1])
                facts = await fetch_all(concepts, str(revenue.get("unit", "USD")).split("/")[0])
    except Exception:
        return None

    if not facts:
        return None
    entity = str(entry.get("title", "")).strip()
    ticker = str(entry.get("ticker", "")).strip()
    figures = "; ".join(
        f"{label} for the fiscal year ending {fact.get('end', '')}"
        f"{f' (FY{fact.get('fy')})' if fact.get('fy') else ''}: "
        f"{format_value(float(fact['val']), str(fact.get('unit', 'USD')))}"
        for label, fact in facts
    )
    newest = max(facts, key=lambda item: str(item[1].get("end", "")))[1]
    accession = str(newest.get("accn", ""))
    return WebSource(
        title=f"SEC EDGAR — {entity} annual financials"[:200],
        url=filing_index_url(cik, accession) if accession
        else f"{_www_base()}/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
        snippet=(
            f"As filed with the SEC by {entity} ({ticker}) in its annual {newest.get('form', '10-K')} report, "
            f"{'IFRS' if taxonomy == 'ifrs-full' else 'US-GAAP'} XBRL: {figures}."
        ),
        provider="sec_edgar",
        freshness="filing",
    )


async def fetch_sec_facts(query: str) -> list[WebSource]:
    """Return one WebSource per resolved concept with the company's own filed
    figure, when the question names a US registrant and a known concept; else []."""
    agent = _user_agent()
    if not agent:
        return []

    concepts = pick_concepts(query)
    generic_filings = bool(_GENERIC_FILING_REQUEST.search(query))
    if not concepts and not generic_filings:
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
            if generic_filings and not concepts:
                response = await client.get(f"{_data_base()}/submissions/CIK{cik:010d}.json")
                response.raise_for_status()
                source = _recent_filings_source(query, company, response.json())
                return [source] if source else []
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
