"""
SearXNG web-search retrieval layer for Ask Kritonâ„¢.

Replaces/augments the governed keyword_mvp source library with live web
search: it queries a SearXNG instance (JSON API), optionally restricting
results to an allowlist of authoritative accounting/tax/audit domains per
jurisdiction, and returns the top hits (title + URL + snippet) that the LLM
then grounds its answer in. Each returned source becomes a clickable
[REF-N] citation in the response.

Design notes:
  - Fails soft: any network/parse error returns an empty list, so a query
    still degrades to a model-knowledge answer (with no source panel)
    instead of erroring out.
  - Allowlist is advisory: if restricting to trusted domains yields nothing,
    it falls back to the unfiltered top results so the bot still answers.
    Set SEARXNG_STRICT_ALLOWLIST=true to disable that fallback.
  - Only snippets (SearXNG's `content` field) are used for grounding, not
    full page fetches — fast and enough for a cited summary. Full-page
    fetching can be layered on later if deeper grounding is needed.
"""
from __future__ import annotations

import asyncio
import json
import dataclasses
import html
import logging
import os
import re
from urllib.parse import urlparse
from dataclasses import asdict, dataclass

from app.domains.calculations.schemas import LiveObservation

import httpx

from app.orchestration.procedures import names_another_procedure
from app.orchestration.source_taxonomy import (
    allowed_domains,
    detect_topics,
    matches_allowlist,
    organisation_key,
    site_filter,
)


@dataclass
class WebSource:
    title: str
    url: str
    snippet: str
    # Provenance metadata, optional so the three original connectors and
    # SearXNG itself keep working unchanged. Set by connectors that know what
    # they returned and how current it is — market data especially, where the
    # difference between a real-time tick, a delayed quote and yesterday's
    # close changes what the answer may claim.
    provider: str | None = None
    fetched_at: str | None = None
    freshness: str | None = None      # realtime | delayed | historical | filing | legislation
    # Internal uploaded documents have no public URL; preserve their stable ID
    # separately so response citations can still resolve to the exact document.
    source_id: str | None = None
    observation: LiveObservation | None = None
    # Structured (period, value) observations behind this source's snippet —
    # set only by connectors that fetched a real numeric time series (see
    # dbnomics.py). Lets orchestration/live_data.py build a chart directly
    # from the fetched data when eligible, instead of relying on the model to
    # correctly re-parse the numbers back out of its own prose or a tool call.
    series: list[tuple[str, float]] | None = None
    # False for a governed passage whose licence allows use but not verbatim
    # display ("summarise"): it stays citable, with no quoted preview.
    preview_allowed: bool = True


logger = logging.getLogger(__name__)


def _searxng_url() -> str:
    return os.getenv("SEARXNG_URL", "http://localhost:8888").rstrip("/")


def _strict_allowlist() -> bool:
    return os.getenv("SEARXNG_STRICT_ALLOWLIST", "").lower() in {"1", "true", "yes"}


# â”€â”€ Result cache â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SearXNG holds no index of its own: it forwards every query to Google and
# DuckDuckGo, both of which rate-limit or CAPTCHA a self-hosted instance that
# asks repeatedly from one address. Development put the same few questions
# through this path dozens of times — "How is federal income tax calculated in
# the US?" went out five times inside twenty minutes — and the instance ended
# up suspended by Google and CAPTCHA'd by DuckDuckGo. Both then answer HTTP 200
# with an empty result list, so every reply silently lost its citations while
# the authorities sat one allowlist away, perfectly reachable.
#
# Caching the repeats is what holds the request rate under whatever trips that.
# Latency is a side benefit: the search is the slowest single step in
# ask_kriton (see its background-task comment) and a hit removes it outright.
#
# Redis, not a process-local dict. The dict emptied on every restart, and
# `uvicorn --reload` restarts on every file save — so a normal afternoon's
# editing handed the same handful of questions back to the engines over and
# over, which is the precise pattern that got the instance blocked. Redis
# outlives reloads, container restarts and redeploys. The cost is roughly a
# millisecond per hit against a search bounded at 6s, which is not a trade
# worth thinking about; durability was the whole reason for the move, not
# speed.
#
# Redis is a declared dependency, but the import is guarded: this module's
# contract is to degrade rather than raise, and a cache that cannot even be
# imported should lose its caching, not take web search down with it.
try:
    import redis.asyncio as _redis
except Exception:                   # pragma: no cover - package absent/broken
    _redis = None

# Bumped whenever WebSource's field set changes. Entries written by an older
# build then simply miss, instead of deserialising into a half-populated
# object that looks valid and cites wrongly.
_CACHE_KEY_PREFIX = "websearch:v4:"

# DB 3: 0 and 1 carry Celery's queue and results, 2 the rate limiter. A
# separate DB means flushing this cache can never drop a queued job.
_CACHE_REDIS_DEFAULT_URL = "redis://localhost:6379/3"

# A stalled Redis has to stay cheaper than the search it exists to avoid.
# Half a second against a 6s bound is the most it is worth waiting before
# giving up and going out to the engines.
_CACHE_SOCKET_TIMEOUT = 0.5


def _cache_ttl() -> float:
    """Seconds a cached result stays usable. 0 or less disables the cache.

    An hour by default: an authority's guidance page reads the same at 11:02 as
    at 11:22, so nothing is lost. Live figures never come through here —
    exchange rates, statistics, filings and market data have their own keyed
    connectors (frankfurter.py, dbnomics.py, fred.py, market_data.py), which
    are not subject to this blocking and must not be served stale.
    """
    try:
        return float(os.getenv("SEARXNG_CACHE_TTL_SECONDS", "3600"))
    except ValueError:
        return 3600.0


def _cache_redis_url() -> str:
    # Compose overrides this with the service name; localhost is for a bare
    # local run. REDIS_URL sits in between so a deployment that provisions one
    # Redis does not need a second variable set.
    return (
        os.getenv("SEARXNG_CACHE_REDIS_URL")
        or os.getenv("REDIS_URL")
        or _CACHE_REDIS_DEFAULT_URL
    )


_redis_client = None
_redis_client_loop = None


def _client():
    """The shared client, or None when Redis is unusable (callers treat that
    as a miss).

    Rebuilt whenever the running event loop changes: redis.asyncio binds its
    connection pool to the loop that created it, and a pool left over from a
    closed loop raises on first use. Production has one long-lived loop and
    builds this once; anything driving the module through repeated
    asyncio.run() gets a fresh client per loop instead of a broken one.
    """
    global _redis_client, _redis_client_loop
    if _redis is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _redis_client is not None and _redis_client_loop is loop:
        return _redis_client
    try:
        _redis_client = _redis.from_url(
            _cache_redis_url(),
            decode_responses=True,
            socket_timeout=_CACHE_SOCKET_TIMEOUT,
            socket_connect_timeout=_CACHE_SOCKET_TIMEOUT,
        )
        _redis_client_loop = loop
    except Exception:
        _redis_client = None
        _redis_client_loop = None
    return _redis_client


def _cache_key(query: str, jurisdiction: str, limit: int) -> str:
    # Jurisdiction and limit belong in the key because both change the result:
    # the allowlist differs per jurisdiction, and limit decides how many
    # sources survive _spread_across_organisations. Whitespace and case are
    # normalised so "Federal  income tax" and "federal income tax" share an
    # entry rather than each making its own trip.
    return (
        f"{_CACHE_KEY_PREFIX}{(jurisdiction or '').strip().upper()}"
        f"|{limit}|{' '.join(query.lower().split())}"
    )


def _encode(results: list[WebSource]) -> str:
    return json.dumps([asdict(s) for s in results], separators=(",", ":"))


def _decode(raw: str) -> list[WebSource]:
    return [WebSource(**item) for item in json.loads(raw)]


async def _cache_get(key: str) -> list[WebSource] | None:
    client = _client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:
        # Refused, down, or past the socket timeout. Fail open: a cache outage
        # costs the search it would have saved, never the answer.
        return None
    if raw is None:
        return None
    try:
        return _decode(raw)
    except Exception:
        # Unreadable entry — hand-edited, truncated, or written by a build
        # whose WebSource had different fields than the prefix claims. Treat
        # it as a miss; the refetch overwrites it.
        return None


async def _cache_put(key: str, results: list[WebSource]) -> None:
    # Deliberately NOT caching an empty result. Empty means either a genuine
    # no-match or a blocked/timed-out engine, and the two are indistinguishable
    # at this layer — SearXNG answers 200 with "results": [] for both. Storing
    # one would pin "no sources" in place for the whole TTL and keep serving it
    # after the block lifted, turning a twenty-minute outage into an hour of
    # uncited answers. Negative caching is the wrong call here even though it
    # is usually the right one.
    if not results:
        return
    ttl = _cache_ttl()
    if ttl <= 0:
        return
    client = _client()
    if client is None:
        return
    try:
        # psetex rather than setex because the TTL is a float and sub-second
        # values are meaningful. Expiry is now the server's job, so there is
        # no sweep here and no entry cap to enforce: the TTL bounds the key
        # count, with maxmemory-policy allkeys-lru as the server-side backstop
        # if the instance is ever shared with something larger.
        await client.psetex(key, max(1, int(ttl * 1000)), _encode(results))
    except Exception:
        # Same reasoning as the read path: a cache that cannot be written is
        # a slower next question, not a failed one.
        return


def _spread_across_organisations(
    sources: list[WebSource], domains: list[str], limit: int
) -> list[WebSource]:
    """Pick `limit` sources spread across as many distinct BODIES as possible.

    Search engines rank by relevance alone, so the top five hits for a UK tax
    question are routinely five pages of the same HMRC manual. That reads as
    five citations while carrying one organisation's view, and it hides the
    standard-setter or the statute that would corroborate (or contradict) it.

    Round-robin over organisations, in the order each first appeared, so the
    engine's own relevance ranking still decides which page represents a body
    and which body leads. Only once every organisation has contributed one
    source does any of them contribute a second — so a five-source answer
    drawn from five bodies stays five bodies, and one drawn from a single
    body is still returned rather than truncated.
    """
    grouped: dict[str, list[WebSource]] = {}
    for source in sources:
        grouped.setdefault(organisation_key(source.url, domains), []).append(source)

    spread: list[WebSource] = []
    round_index = 0
    while len(spread) < limit and any(len(v) > round_index for v in grouped.values()):
        for bucket in grouped.values():
            if len(bucket) > round_index:
                spread.append(bucket[round_index])
                if len(spread) == limit:
                    return spread
        round_index += 1
    return spread


# ── Reading the pages behind the top sources ────────────────────────────────
# A search result carries a ~150-character snippet — the page's title line,
# e.g. "Tax rates (For AY 2025-26 and 2026-27) · Tax rates for last 10 years".
# The figures a question asks for (a slab table, a threshold) are on the page,
# not in the snippet, so the model filled them from stale memory and cited the
# official page for them. The top official/trusted pages are now read and the
# relevant part (tables kept row by row) is passed on instead.
_PAGE_TIMEOUT_SECONDS = 4.0
_PAGE_MAX_BYTES = 2_000_000
_PAGE_EXCERPT_CHARS = 3000
_OFFICIAL_HOST = re.compile(
    r"(?:^|\.)(?:gov|gov\.[a-z]{2}|gc\.ca|nic\.in|europa\.eu|ifrs\.org|fasb\.org|"
    r"iaasb\.org|icai\.org|oecd\.org|worldbank\.org|imf\.org|legislation\.gov\.uk)$"
)
_EXCERPT_STOPWORDS = {
    "what", "which", "when", "where", "does", "under", "with", "from", "this", "that",
    "their", "there", "about", "rate", "rates", "india", "current", "latest",
}


def _readable_host(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme not in {"http", "https"} or not host:
        return False
    return bool(_OFFICIAL_HOST.search(host)) or matches_allowlist(url, domains)


_ANY_SPACE = re.compile(r"[\s   -​  　﻿]+")
_CELL = re.compile(r"(?is)<t([dh])\b([^>]*)>(.*?)</t[dh]\s*>")
_COLSPAN = re.compile(r"""(?i)colspan\s*=\s*["']?(\d+)""")
_HAS_FIGURE = re.compile(r"[₹$£€]|\d\s?%|\d{1,3}(?:,\d{2,3})+")


def _cell_text(fragment: str) -> str:
    return _ANY_SPACE.sub(" ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _table_to_text(match: re.Match) -> str:
    """One line per data row with every cell labelled by its column heading
    ("New Tax Regime – Income Tax Slab: Up to ₹ 4,00,000; …"). A two-level
    header over side-by-side columns — Old | New regime, each with Slab | Rate
    — otherwise leaves the model guessing which figures belong to which
    regime, and it read the old-regime column as the answer."""
    rows: list[list[str]] = []
    header_flags: list[bool] = []
    for row in re.findall(r"(?is)<tr\b.*?</tr\s*>", match.group(0)):
        cells: list[str] = []
        all_th = True
        for kind, attrs, body in _CELL.findall(row):
            span = int(_COLSPAN.search(attrs).group(1)) if _COLSPAN.search(attrs) else 1
            cells.extend([_cell_text(body)] * max(1, min(span, 12)))
            all_th = all_th and kind.lower() == "h"
        if cells:
            rows.append(cells)
            header_flags.append(all_th or not any(_HAS_FIGURE.search(cell) for cell in cells))
    header_count = 0
    while header_count < min(2, len(rows) - 1) and header_flags[header_count]:
        header_count += 1
    width = max((len(row) for row in rows), default=0)
    labels = []
    for column in range(width):
        parts: list[str] = []
        for row in rows[:header_count]:
            if column < len(row) and row[column] and row[column] not in parts:
                parts.append(row[column])
        labels.append(" – ".join(parts))
    lines = []
    for row in rows[header_count:]:
        if header_count:
            lines.append("; ".join(f"{labels[i]}: {cell}" if labels[i] else cell for i, cell in enumerate(row) if cell))
        else:
            lines.append(" | ".join(cell for cell in row if cell))
    return "\n" + "\n".join(lines) + "\n"


def _html_to_text(markup: str) -> str:
    """Visible text with structure kept: tables become one labelled line per
    row (see _table_to_text); other blocks become lines."""
    markup = re.sub(r"(?is)<(script|style|noscript|head|nav|footer|svg)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?is)<table\b.*?</table\s*>", _table_to_text, markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(?:p|li|h[1-6]|div|section|caption)\s*>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    lines = (_ANY_SPACE.sub(" ", line).strip(" |") for line in text.splitlines())
    return "\n".join(line for line in lines if line)


_FIGURE = re.compile(r"[₹$£€]\s?\d|\d\s?%|\d{1,3}(?:,\d{2,3})+")
# Small windows so a compact table outscores prose around it; ties go to
# the earliest window (the main table precedes age-band variants).
_EXCERPT_WINDOW = 12


def _relevant_excerpt(text: str, query: str, limit: int = _PAGE_EXCERPT_CHARS) -> str:
    """The densest part of the page for this question: windows of lines are
    scored by query terms and figures (amounts, %), and the best windows are
    kept in page order. Repeated lines (menus, "Tax slabs" x10) are dropped
    first so they cannot use up the budget."""
    terms = {
        word.lower() for word in re.findall(r"[A-Za-z]{4,}|\d{2,4}(?:-\d{2})?", query)
    } - _EXCERPT_STOPWORDS
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        if line not in seen:
            seen.add(line)
            lines.append(line)
    if not lines:
        return ""
    # Stem plurals ("slabs" must match the page's "Income Tax Slab"), weight a
    # term by how rare it is on the page (a word on every line, like "income"
    # on a tax page, says little), and favour lines carrying figures — the
    # rates and thresholds a question asks for live in tables of amounts.
    terms = {term[:-1] if len(term) > 4 and term.endswith("s") else term for term in terms}
    lowered = [line.lower() for line in lines]
    weight = {
        term: 3.0 / max(1.0, sum(1 for line in lowered if term in line) / 4)
        for term in terms
    }
    scores = [
        sum(weight[term] for term in terms if term in line) + (2 if _FIGURE.search(original) else 0)
        for line, original in zip(lowered, lines)
    ]
    starts = range(0, max(1, len(lines) - _EXCERPT_WINDOW + 1), 3)
    ranked = sorted(starts, key=lambda start: -sum(scores[start:start + _EXCERPT_WINDOW]))
    keep: set[int] = set()
    used = 0
    for start in ranked:
        if sum(scores[start:start + _EXCERPT_WINDOW]) == 0 or used >= limit:
            break
        for index in range(start, min(start + _EXCERPT_WINDOW, len(lines))):
            if index not in keep and used + len(lines[index]) <= limit:
                keep.add(index)
                used += len(lines[index]) + 1
    return "\n".join(lines[index] for index in sorted(keep))


async def _read_html(client: httpx.AsyncClient, url: str) -> str:
    # Headers first: a non-HTML document (a multi-MB World Bank PDF) used to
    # be downloaded in full before being discarded, holding a search for 13s+.
    async with client.stream("GET", url) as response:
        if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            return ""
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _PAGE_MAX_BYTES:
                return ""
        return bytes(body).decode(response.encoding or "utf-8", errors="replace")


async def _page_excerpt(client: httpx.AsyncClient, url: str, query: str) -> str:
    try:
        # httpx's timeout is per read, so a slowly trickling page could run
        # far past it; this bounds the whole read.
        html = await asyncio.wait_for(_read_html(client, url), timeout=_PAGE_TIMEOUT_SECONDS)
        return _relevant_excerpt(_html_to_text(html), query) if html else ""
    except Exception:  # noqa: BLE001 — a page that can't be read keeps its search snippet
        return ""


async def _with_page_extracts(
    sources: list[WebSource], query: str, domains: list[str], pages: int,
) -> list[WebSource]:
    """Replace the snippet of the top `pages` official/trusted sources with the
    relevant part of the page itself. Fail-soft: a slow or failing page keeps
    its search snippet. Only official or allowlisted hosts are fetched."""
    targets = [i for i, source in enumerate(sources) if _readable_host(source.url, domains)][:pages]
    if not targets:
        return sources
    async with httpx.AsyncClient(
        timeout=_PAGE_TIMEOUT_SECONDS, follow_redirects=True, max_redirects=3,
        headers={"User-Agent": "Mozilla/5.0 (compatible; KritonResearch/1.0)"},
    ) as client:
        excerpts = await asyncio.gather(*(_page_excerpt(client, sources[i].url, query) for i in targets))
    enriched = list(sources)
    for index, excerpt in zip(targets, excerpts):
        if len(excerpt) > len(sources[index].snippet):
            enriched[index] = dataclasses.replace(sources[index], snippet=f"{sources[index].snippet}\n[From the page]\n{excerpt}")
    return enriched


_RELEVANCE_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have how i if in into is it its
may me might my no not of on or our should so than that the their them then there these they this those to
was we were what when where which who whom why will with would you your about after before also any each
just like more most much only other over same some such very year years per one two three uk us usa india
under between within without upon among against through during above below across along around beyond
section sections act rule rules explain describe difference differ
""".split())
# "under", "section" and "act" matched dictionary pages ("UNDER Definition &
# Meaning") to "Under Section 44AB of the Income-tax Act…", and those pages
# were cited as the answer's sources.


def _terms(text: str) -> set[str]:
    # Five-letter stems so "invest"/"investment" and "audit"/"auditor" meet.
    return {
        word[:5] for word in re.findall(r"[a-z][a-z0-9]+", text.lower())
        if len(word) >= 3 and word not in _RELEVANCE_STOPWORDS
    }


_HISTORY_PAGE = re.compile(r"\b(?:previous changes|historic(?:al)? (?:rates|changes|information)|archived?|superseded|withdrawn)\b", re.I)
_ASKS_ABOUT_HISTORY = re.compile(
    r"\b(?:previous(?:ly)?|historic(?:al)?|history|used to|old|former(?:ly)?|before|in (?:19|20)\d\d|(?:19|20)\d\d)\b", re.I,
)


_QUERY_FILLER = re.compile(
    r"\b(?:what|how|why|when|where|which|who|does|do|did|is|are|was|were|can|could|should|would|"
    r"the|a|an|of|in|on|for|to|and|or|under|between|differ|difference|from|with|by|its|their|"
    r"explain|describe|tell|me|please|terms|requirement|requirements)\b", re.I)


def _keyword_query(query: str) -> str:
    """The question without filler words: "How does Section 44AD differ from
    Section 44ADA?" -> "Section 44AD Section 44ADA"."""
    return " ".join(_QUERY_FILLER.sub(" ", re.sub(r"[?,.;:()]", " ", query or "")).split())


def _is_relevant(query: str, source: WebSource) -> bool:
    """A result must be about the question, not merely hosted by a trusted body.

    The site: bias returns whatever a trusted domain has: a compound-interest
    question came back with five OECD/ILO reports (a health survey, a garment
    sector study) that were then cited as the answer's sources. A result is
    kept when its title shares a meaningful word with the question, or its
    title and snippet together share two."""
    wanted = _terms(query)
    # A page about a different procedure on the same tax (a VAT refund page
    # for a VAT-return question) — see app/orchestration/procedures.py.
    if names_another_procedure(query, source.title):
        return False
    # A page recording superseded rules (HMRC "VCAS9450 - Previous changes")
    # states old figures as plainly as current ones: a "when must I leave
    # cash accounting?" answer gave the old £437,500 tolerance as the rule.
    if _HISTORY_PAGE.search(source.title) and not _ASKS_ABOUT_HISTORY.search(query):
        return False
    return bool(wanted & _terms(source.title)) or len(wanted & _terms(f"{source.title} {source.snippet}")) >= 2


_EMPTY_RETRY_DELAY_SECONDS = 1.5
# Everything web_search does must finish inside the orchestration's 12s
# search timeout, or the whole result is discarded.
_SEARCH_BUDGET_SECONDS = 9.5


async def _searxng_results(base: str, params: dict) -> list[dict]:
    """One SearXNG query, retried once when it comes back empty.

    The public engines behind SearXNG throttle bursts (CAPTCHA, "too many
    requests"), and SearXNG then answers 200 with no results — a question
    asked seconds after another lost all its sources. A short pause and one
    retry rides out the brief throttles; a longer suspension still fails soft.
    The retry is skipped when the first attempt was slow, so the caller's
    overall search timeout is never exceeded."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{base}/search", params=params)
                resp.raise_for_status()
                results = resp.json().get("results", []) or []
        except Exception:
            results = []
        if results or attempt == 1 or loop.time() - started > 3.0:
            return results
        await asyncio.sleep(_EMPTY_RETRY_DELAY_SECONDS)
    return []


def _tavily_key() -> str:
    return (os.getenv("TAVILY_API_KEY") or "").strip()


_TAVILY_URL = "https://api.tavily.com/search"


async def _tavily_results(query: str, domains: list[str]) -> list[dict] | None:
    """Search through Tavily, restricted to the trusted domains when there are
    any and widened to the open web only when they hold nothing (unless the
    allowlist is strict). Results come back in SearXNG's shape (url, title,
    content) so everything downstream is unchanged.

    Tavily is preferred over SearXNG because the free engines behind SearXNG
    block a self-hosted instance (CAPTCHA, "too many requests") for minutes at
    a time, and every answer in that window lost its sources. None means
    Tavily is not configured or failed, so the caller falls back to SearXNG;
    [] means it searched and found nothing."""
    key = _tavily_key()
    if not key:
        return None
    # Advanced depth on the trusted domains: basic depth returned OECD reports
    # for "GST rate on restaurant services in India" where advanced found the
    # CBIC rate notification. The open-web fallback is a quick basic search,
    # so the two together stay inside the caller's search timeout.
    attempts = [(domains, "advanced")] if domains else []
    if not domains or not _strict_allowlist():
        attempts.append(([], "basic"))
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            for include, depth in attempts:
                body = {"query": query, "max_results": 10, "search_depth": depth}
                if include:
                    body["include_domains"] = include
                resp = await client.post(_TAVILY_URL, headers={"Authorization": f"Bearer {key}"}, json=body)
                resp.raise_for_status()
                results = resp.json().get("results", []) or []
                if results:
                    return [
                        {"url": r.get("url"), "title": r.get("title"), "content": r.get("content")}
                        for r in results
                    ]
    except Exception as exc:
        logger.warning("Tavily search failed (%s); trying the next provider", type(exc).__name__)
        return None
    return []


async def web_search(query: str, jurisdiction: str = "", limit: int = 5, read_pages: int = 2) -> list[WebSource]:
    """Search the web (Tavily when TAVILY_API_KEY is set, else SearXNG) and
    return up to `limit` sources, preferring trusted domains for the
    jurisdiction and topic. Returns [] on any failure (fail-soft).

    Successful results are cached in Redis for SEARXNG_CACHE_TTL_SECONDS so a
    repeated question does not make a second trip to the upstream engines —
    see the cache block above for why that matters more than the latency it
    saves. An unreachable cache degrades to a normal search.
    """
    # read_pages changes the result (page excerpts), so it is part of the key.
    cache_key = f"{_cache_key(query, jurisdiction, limit)}:pages={read_pages}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached
    started = asyncio.get_running_loop().time()

    base = _searxng_url()
    # Topic narrows the allowlist from "every body in this jurisdiction" to
    # the ones with authority over THIS question (source_taxonomy.py). An
    # off-taxonomy question detects no topics, which yields the full
    # jurisdiction list — the behaviour before topics existed.
    domains = allowed_domains(jurisdiction, detect_topics(query), query)
    # Bias retrieval toward those bodies up front. Filtering alone only drops
    # results after the fact, so a narrow question could return twenty blog
    # posts, lose all of them, and fall through to untrusted general results.
    sites = site_filter(domains)
    params = {
        "q": f"{query} {sites}".strip() if sites else query,
        "format": "json",
        "safesearch": "1",
        "categories": "general",
    }
    # Tavily returns None when it is not configured or failed; SearXNG
    # (self-hosted) is then the backup.
    results = await _tavily_results(query, domains)
    used_backup = results is None
    if used_backup:
        results = await _searxng_results(base, params)

    def relevant(raw: list[dict]) -> list[WebSource]:
        """Entries with a usable URL that are actually about the question."""
        found: list[WebSource] = []
        for r in raw:
            url = (r.get("url") or "").strip()
            if not url:
                continue
            source = WebSource(
                title=(r.get("title") or url)[:200],
                url=url,
                snippet=(r.get("content") or "").strip(),
            )
            if _is_relevant(query, source):
                found.append(source)
        return found

    parsed = relevant(results)
    trusted = [s for s in parsed if matches_allowlist(s.url, domains)]
    # The public engines behind the backup match a full question poorly:
    # "Under Section 44AB of the Income-tax Act…" returned dictionary pages
    # for "under", and "How does Section 44AD differ from Section 44ADA?"
    # nothing usable. With no trusted result, one retry with only the key
    # terms, restricted to the same official sites.
    keywords = _keyword_query(query)
    if used_backup and not trusted and keywords and keywords.lower() != query.lower():
        retry = await _searxng_results(base, {**params, "q": f"{keywords} {sites}".strip() if sites else keywords})
        retry_parsed = relevant(retry)
        retry_trusted = [s for s in retry_parsed if matches_allowlist(s.url, domains)]
        if retry_trusted or not parsed:
            parsed, trusted = retry_parsed, retry_trusted

    if trusted:
        selected = _spread_across_organisations(trusted, domains, limit)
    elif _strict_allowlist():
        selected = []
    else:
        # Fallback: no trusted-domain hits — return the general top results so
        # the bot still answers (allowlist is advisory unless
        # SEARXNG_STRICT_ALLOWLIST). Spread these too: organisation_key falls
        # back to the bare hostname off the allowlist, so five pages of one
        # blog still collapse to one voice.
        selected = _spread_across_organisations(parsed, domains, limit)

    # Cached AFTER filtering and spreading, so the stored value is what a
    # caller would have received. Caching the raw engine response instead would
    # freeze today's allowlist into every future hit, and a taxonomy change
    # would not take effect until the entries aged out.
    # The top official/trusted pages are read and their relevant part passed
    # on (see _with_page_extracts); cached with the excerpts, so a repeat
    # question does not re-read the pages either.
    # Reading pages is an enrichment, so it gets only the time left before
    # the caller's search timeout (12s in orchestration); past that, the
    # search snippets are returned as they are rather than losing everything.
    remaining = _SEARCH_BUDGET_SECONDS - (asyncio.get_running_loop().time() - started)
    if remaining > 1.0:
        try:
            selected = await asyncio.wait_for(
                _with_page_extracts(selected, query, domains, read_pages), timeout=remaining,
            )
        except asyncio.TimeoutError:
            pass
    # Only results with a trusted source are cached. Untrusted fallback
    # results are what a degraded moment produces: with Tavily timing out,
    # SearXNG answered "What is the due date for GSTR-3B?" with dictionary
    # pages for "due", and caching them served that junk (filtered to no
    # sources downstream) for the whole TTL.
    if trusted:
        await _cache_put(cache_key, selected)
    return selected


# Several questions in one message ("What are the FY 2025-26 slabs? What is
# the standard deduction? What is the UK VAT threshold? …") searched as ONE
# query returned pages matching none of them well — a meal-voucher blog, an
# exam paper — so most parts were answered "not in the sources" or from stale
# memory. Each question is searched on its own, as a person would.
_QUESTION_BOUNDARY = re.compile(r"(?<=\?)\s+")
MAX_SUB_QUESTIONS = 8
_SOURCES_PER_SUB_QUESTION = 3
# The public engines behind SearXNG throttle bursts (see web_search), so the
# per-question searches run a few at a time rather than all at once. The
# hosted API (Tavily) takes a burst, so every part runs at once: six
# questions three at a time took 12s, reached the orchestrator's 12s web
# search limit, and the answer lost all fifteen sources it had found.
_SUB_SEARCH_CONCURRENCY = 3
_HOSTED_SUB_SEARCH_CONCURRENCY = 6
# Each part's own deadline, inside the orchestrator's 12s: a slow part
# returns nothing instead of discarding the parts that finished.
_SUB_SEARCH_TIMEOUT_SECONDS = 10.0


def question_count(query: str) -> int:
    """How many separate questions a message asks (before the search cap)."""
    parts = [part.strip() for part in _QUESTION_BOUNDARY.split((query or "").strip()) if part.strip()]
    return max(1, len([part for part in parts if len(part.split()) >= 3]))


def sub_questions(query: str) -> list[str]:
    """The separate questions in a message, or [query] when it holds one."""
    parts = [part.strip() for part in _QUESTION_BOUNDARY.split(query.strip()) if part.strip()]
    parts = [part for part in parts if len(part.split()) >= 3]
    return parts[:MAX_SUB_QUESTIONS] if len(parts) >= 2 else [query]


async def _uk_vat_rules_source() -> list[WebSource]:
    """Read the official decision rules, not a ranked snippet of their introduction."""
    url = "https://www.gov.uk/register-for-vat"
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=False,
                                     headers={"User-Agent":"KritonResearch/1.0"}) as client:
            markup = await asyncio.wait_for(_read_html(client, url), timeout=5.0)
        text = _html_to_text(markup)
        start = text.find("You must register if either")
        if start < 0:
            return []
        rules = _uk_vat_registration_excerpt(text[start:start+8000])
        return [WebSource(title="HMRC: When to register for VAT", url=url,
                          snippet=rules, provider="GOV.UK (HMRC)", freshness="current")]
    except Exception:
        return []


def _uk_vat_registration_excerpt(text: str) -> str:
    """Keep both domestic triggers and deadlines together in the verifier budget.

    Ranking the whole page dropped the short prospective deadline while
    retaining unrelated Northern Ireland and overseas-business rules.
    These are verbatim sentences, never generated or remembered tax facts.
    """
    flattened = " ".join(text.split())
    passages = []
    for pattern in (
        r"You must register if your total taxable turnover for the last 12 months[^.]*\.",
        r"You have to register within 30 days[^.]*\.",
        r"You must register if you realise that your total taxable turnover[^.]*\.",
        r"You (?:must|have to) register by the end of (?:that|the) 30[- ]day period[^.]*\.",
    ):
        match = re.search(pattern, flattened, re.I)
        if not match:
            return text
        passages.append(match.group(0))
    return "\n".join(passages)


async def web_search_each(query: str, jurisdiction: str = "", limit: int = 5) -> list[WebSource]:
    """web_search for a single question; for a message with several questions,
    one search per question (bounded concurrency), merged without duplicates
    so every part of the answer has sources of its own."""
    parts = evidence_search_queries(query)
    hosted = bool(_tavily_key())
    gate = asyncio.Semaphore(_HOSTED_SUB_SEARCH_CONCURRENCY if hosted else _SUB_SEARCH_CONCURRENCY)

    async def search(part: str) -> list[WebSource]:
        from app.orchestration.source_taxonomy import detect_jurisdictions
        named = detect_jurisdictions(part)
        part_jurisdiction = named[0] if len(named) == 1 else jurisdiction
        async with gate:
            try:
                return await asyncio.wait_for(
                    web_search(part, jurisdiction=part_jurisdiction, limit=limit if len(parts) == 1 else _SOURCES_PER_SUB_QUESTION, read_pages=1),
                    timeout=_SUB_SEARCH_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("Sub-question search timed out; other parts keep their sources")
                return []

    merged: list[WebSource] = []
    seen: set[str] = set()
    from app.orchestration.input_requirements import uk_vat_rules_requested
    from app.orchestration.official_evidence import official_sources
    from app.orchestration.source_taxonomy import detect_jurisdictions
    searches = [search(part) for part in parts]
    searches.insert(0, official_sources(query))
    if uk_vat_rules_requested(query) or (
        'UK' in detect_jurisdictions(query) and re.search(r'\bvat\b', query, re.I)
        and re.search(r'\b(?:threshold|register|registration)\b', query, re.I)
    ):
        searches.insert(0, _uk_vat_rules_source())
    for group in await asyncio.gather(*searches):
        for source in group:
            if source.url not in seen:
                seen.add(source.url)
                merged.append(source)
    return merged


def evidence_search_queries(query: str) -> list[str]:
    """Cover the decision rules, not just an application form or narrow FAQ."""
    if re.search(r"\b(?:vat|gst)\b", query, re.I) and re.search(r"\brates?\b", query, re.I) and not re.search(r"\bregistration\b", query, re.I):
        from app.orchestration.source_taxonomy import detect_jurisdictions
        countries = detect_jurisdictions(query)
        if len(countries) > 1:
            # Research rates separately from the supplied calculation amounts:
            # '1,000' otherwise ranked import/customs limits above general rates.
            years = re.findall(r'\b(?:19|20)\d{2}\b', query)
            period = ' '.join(years) if years else 'current'
            if not years and re.search(r'\b(?:historical|last year|previous year)\b', query, re.I):
                return sub_questions(query)
            return [f"{country.replace('_', ' ')} {period} standard VAT GST rate official tax authority"
                    for country in countries]
    if re.search(r"\bregistration\b", query, re.I):
        markets = [("Australia", "Australia ATO GST registration current projected GST turnover 75000 150000 exceptions"),
                   ("Singapore", "Singapore IRAS domestic compulsory GST registration retrospective prospective taxable turnover 1 million"),
                   ("UK", "UK HMRC VAT registration taxable turnover rolling 12 months next 30 days threshold")]
        found = [term for name,term in markets if re.search(r"\b" + ("(?:uk|united kingdom)" if name == "UK" else name) + r"\b", query, re.I)]
        if len(found) > 1:
            return found
        from app.orchestration.input_requirements import uk_vat_rules_requested
        if uk_vat_rules_requested(query):
            return [query, "site:gov.uk/register-for-vat taxable turnover last 12 months expected next 30 days",
                    "site:gov.uk/register-for-vat register within 30 days end month effective date next 30 day period"]
    if re.search(r"\b(?:india|indian|bangalore|bengaluru|karnataka)\b", query, re.I) and re.search(r"\bgst\b", query, re.I):
        india_parts = [query]
        if re.search(r"\bregistration\b", query, re.I):
            india_parts += [
                "India GST registration aggregate turnover thresholds goods services state notification 10/2019 current",
                "India CGST Act section 23 section 24 compulsory registration interstate services exemption notification 10/2017 Integrated Tax"]
        if re.search(r"\b(?:export|exports|outside india|foreign|overseas|us client|uk client|abroad)\b", query, re.I):
            # "Billing a US client — do I charge GST?" found the registration
            # threshold but not the zero-rating rule for exported services.
            india_parts += ["India IGST Act section 16 zero rated supply export of services letter of undertaking LUT without payment of IGST",
                            "India IGST Act section 2(6) export of services conditions supplier recipient place of supply payment foreign exchange Indian rupees RBI",
                            "India DGFT services exports IEC necessary only Foreign Trade Policy benefits specified services technology"]
        if len(india_parts) > 1:
            return india_parts
        if re.search(r"\b(?:input tax credit|itc)\b", query, re.I):
            return [query, "India CGST section 16 input tax credit conditions tax paid return furnished section 17 blocked credits current"]
    return sub_questions(query)


# The table/formula formatting rules apply whether or not web sources were
# found — so they live in one shared block that BOTH prompt branches include.
#
# Diagram/chart production (Mermaid + fenced ```chart JSON) was deliberately
# removed from here — visualization is now handled by a deterministic,
# evidence-backed pipeline server-side (orchestration/visualization/), which
# builds charts straight from structured data rather than asking the LLM to
# author them freely. Asking the model to also emit visuals risked disagreeing
# with that pipeline's numbers, and most non-numeric "diagram" requests (org
# charts, flowcharts) had no real backing data to draw from either — see the
# session's earlier data-honesty discussion. If diagram support is wanted
# again, it should route through a similarly evidence-backed, validated path
# rather than free-text LLM authorship.
_FORMATTING_INSTRUCTIONS = (
    "Markdown table rows must have the same number of cells as their header. "
    "Put citations inside a cell or add a Sources column to both the header and every row. "
    "Write percentage rates with a percent sign; label calculated amounts with their local currency. "
    "Keep missing-evidence rows inside the table with complete pipe delimiters. "
    "Answer every requested part, including every country, scenario and table column. "
    "Distinguish general domestic registration from special overseas-vendor and low-value-goods rules. "
    "A customs value limit is not a business turnover registration threshold. Preserve AND/OR conditions exactly. "
    "Never infer an unconditional exemption from turnover alone when country, period or exceptions are missing. "
    "For ordinary credit sales, do not assume a significant financing component or interest accrual. "
    "For illustrative cash flow, include all stated cash payments and state which expenses were paid in cash. "
    "Reducing-balance and double-declining balance are not synonyms; double-declining is one variant. "
    "Return only the user-facing answer. Never print internal routing labels "
    "such as 'CLASSIFICATION:', 'CLASSIFIED:', or 'ANSWER:'. Start directly "
    "with the answer content. Do not use double-asterisk Markdown emphasis; "
    "use plain text or Markdown headings instead.\n"
    # "0.144714 → rounded to 0.14 (14 %)" presented a 14.47% CAGR as 14%.
    "Give percentages and rates to two decimal places (for example 14.47%), never "
    "rounded to a whole number unless the value is a whole number.\n"
    # "The standard GST rate in Malaysia is 6%" — GST was abolished in 2018.
    "For export-of-services qualification give the actual statutory conditions, not an LUT as a substitute. "
    "Do not make a goods-export checklist mandatory for service exporters. Distinguish IGST-paid refunds from unutilised ITC refunds under LUT/bond. "
    "For compulsory-registration questions explain mandatory categories and relevant exemptions separately from turnover thresholds. "
    "If the evidence shows a tax, rate or rule was abolished, replaced or superseded, "
    "say so and give what replaced it if the evidence states it; never present a past "
    "rate as current.\n"
        "When the user requests a chart, graph, heatmap, distribution, "
        "histogram, box plot, spread, or other visualization of a real "
        "numeric data series, a separate validated renderer handles it. Do "
        "not substitute a markdown data table, recommend third-party "
        "drawing tools, describe a hypothetical image, invent "
        "values/relationships, or re-list every individual data point "
        "yourself — give only a concise 1-2 sentence interpretation of the "
        "supplied evidence (e.g. the overall range or direction), not a full "
        "restatement of it.\n"
        "When the user requests a flowchart, workflow diagram, or process "
        "diagram, whether one actually renders is decided automatically, "
        "separately from your answer — your wording has no effect on it "
        "either way, so never mention a diagram, renderer, image, or "
        "visualization anywhere in your answer for this kind of request — "
        "not to promise one, not to say one 'will be shown separately' or "
        "'handled elsewhere', and not to note that one is absent or wasn't "
        "provided either. Just explain the process in prose or a numbered "
        "list, "
        "exactly as you would if visuals didn't exist as a feature.\n"
        "When the user asks for the exact/precise values of a real numeric "
        "data series already given as sources (not a comparison of different "
        "items), the exact-values table is rendered separately and "
        "automatically — give a short 1-2 sentence summary instead of "
        "re-listing every value yourself.\n"
        "When the user asks for a table, a comparison, 'tabular format', or the "
        "content is naturally a comparison of two or more DIFFERENT items across "
        "attributes (not a single data series' own values over time), present it "
        "as a GitHub-flavoured Markdown table using pipe "
        "syntax — a header row like '| Attribute | Option A | Option B |', then "
        "a separator row '| --- | --- | --- |', then one row per attribute. Keep "
        "cell text concise.\n"
        "For complex mathematical formulas, use LaTeX so they "
        "render cleanly: wrap an INLINE formula in \\( ... \\) (e.g. "
        "\\( Depreciation = (Cost - Salvage) / Life \\)), and put a "
        "standalone/display equation on its own line wrapped in double dollar "
        "signs $$...$$. NEVER use a single $ for maths: a single $ always means "
        "US dollars (write $480,000 as plain text). Show the "
        "calculation steps clearly, one step per line, substituting the actual "
        "numbers so the working is easy to follow.\n"
        "A plain currency amount or price in ordinary prose (a stock price, "
        "exchange rate, account balance, etc.) is NOT a LaTeX formula — never "
        "write it with a leading bare $ (not \"$232.11\", not \"$232.11 on "
        "July 24... $231.39 on July 27\"). The renderer treats everything "
        "between two $ signs as one LaTeX span, so two dollar-prefixed prices "
        "in the same answer silently mangles both prices and everything "
        "between them into garbled text. Write currency amounts as \"232.11 "
        "USD\" or \"USD 232.11\" instead — reserve $...$ strictly for an "
        "actual mathematical formula or equation, never a bare number.\n"
)

# Always sent: cheap, and a table or a formula can be the right shape for any
# answer.
_CORE_FORMATTING = (
        # Restored from Naresh-new (1f69f7e, 22b0e4d, 188a6ad); lost when main's
        # rewrite of this block was merged.
        "If the message contains several questions or tasks, answer EVERY one, in "
        "order, each under its own short heading — including any chart or table it "
        "asks for; never answer only the first or skip one. If the user supplies "
        "their own answer (e.g. '… → 36%'), work the question out independently, "
        "show the working, and say whether their answer is correct — never reply "
        "with a bare 'correct'.\n"
        "For EVERY calculation, however simple, show the working step by step "
        "(inputs, formula, each intermediate result, final answer) — never state only "
        "the result. Write thousands separators as commas, never spaces: Indian "
        "grouping for every rupee amount, whether written ₹ or INR (₹10,92,600 / "
        "10,92,600 INR), and international grouping otherwise ($1,092,600).\n"
        "Lead with the direct answer or result. Use concise paragraphs, and only add "
        "## headings when the answer needs sections. Never print internal subject-matter "
        "classification labels.\n"
        "When the user asks for a table, a comparison, 'tabular format', or the "
        "content is naturally a comparison of two or more items across "
        "attributes, present it as a GitHub-flavoured Markdown table using pipe "
        "syntax — a header row like '| Attribute | Option A | Option B |', then "
        "a separator row '| --- | --- | --- |', then one row per attribute. Keep "
        "cell text concise.\n"
        "A table MUST start at the beginning of the line with a BLANK LINE "
        "before it and after it, and its rows must NOT be indented. An indented "
        "table is rendered as a block of monospaced source code, and a table "
        "with no blank line above it is absorbed into the paragraph above, so "
        "in both cases the reader sees rows of literal pipe characters instead "
        "of a table. Never indent table rows to sit them under a heading or a "
        "numbered point — leave them flush left.\n"
        "For complex mathematical formulas, use LaTeX so they "
        "render cleanly: wrap an INLINE formula in \\( ... \\) (e.g. "
        "\\( Depreciation = (Cost - Salvage) / Life \\)), and put a "
        "standalone/display equation on its own line wrapped in double dollar "
        "signs $$...$$. NEVER use a single $ for maths: a single $ always means "
        "US dollars (write $480,000 as plain text). Show the "
        "calculation steps clearly, one step per line, substituting the actual "
        "numbers so the working is easy to follow.\n"
        "Do NOT end the answer with your own disclaimer, caveat or "
        "'consult a professional' closing paragraph. The application "
        "adds its own safety notice outside your output, so anything you "
        "add there is a duplicate — finish on the substance of the "
        "answer instead. (You may still answer a question that is "
        "genuinely ABOUT disclaimers, e.g. what wording an audit report "
        "should carry.)\n"
)

# Sent only for questions that ask for a visual.
_VISUAL_INSTRUCTIONS = (
        "If the user asks for a diagram, chart, workflow, flowchart, process, "
        "decision tree, org chart, hierarchy, tree, architecture, data model, "
        "mind map, timeline, risk matrix, or a proportion/allocation "
        "breakdown, include it as a "
        "Mermaid diagram inside a fenced ```mermaid code block, alongside a "
        "short text explanation. THE OPENING FENCE MUST BE EXACTLY ```mermaid "
        "— a bare ``` fence, or one labelled text/plaintext, is displayed to "
        "the reader as monospace source code instead of being drawn as a "
        "diagram, which is the one outcome to avoid. Choose the Mermaid "
        "diagram type that best fits the request:\n"
        "- 'flowchart TD' (top-down) for processes, workflows, the accounting "
        "cycle, decision trees, org charts / organisation hierarchies and tree "
        "breakdowns (e.g. a balance-sheet structure);\n"
        "- 'flowchart LR' (left-to-right) when the flow reads better "
        "horizontally;\n"
        "- 'sequenceDiagram' for step-by-step interactions between parties "
        "(e.g. a tax-filing exchange);\n"
        "- 'stateDiagram-v2' for statuses and transitions (e.g. an invoice "
        "approval or escalation lifecycle);\n"
        "- 'mindmap' for a mind map / concept breakdown of a topic;\n"
        "- 'gantt' for schedules with DURATIONS (e.g. an audit plan);\n"
        "- 'timeline' for dated milestones with no duration (e.g. a filing "
        "calendar), with rows like '2024-01 : VAT return due';\n"
        "- 'erDiagram' for data models and entity relationships (e.g. how "
        "Invoice, Customer and Payment relate), with rows like "
        "'CUSTOMER ||--o{ INVOICE : places';\n"
        "- 'architecture-beta' for system, service or ERP-module architecture "
        "— declare 'group name(icon)[Label]', then "
        "'service id(icon)[Label] in name', then edges like 'a:R -- L:b';\n"
        "- 'C4Context' or 'C4Container' when a FORMAL layered architecture is "
        "asked for, using Person(), System(), Container() and Rel();\n"
        "- 'block-beta' for a layered stack (e.g. a technology or control "
        "stack), using 'columns N' then block ids;\n"
        "- 'quadrantChart' for a 2x2 matrix such as a risk or impact/"
        "likelihood grid, with 'x-axis', 'y-axis', 'quadrant-1'..'quadrant-4' "
        "and rows like 'Fraud risk: [0.8, 0.9]' (values 0-1);\n"
        "- 'journey' for a user/client journey with satisfaction scores;\n"
        "- 'kanban' for work grouped into status columns;\n"
        "- 'pie title <Title>' for a simple proportion or allocation "
        "breakdown (e.g. budget allocation), with rows like \"Label\" : 40.\n"
        "For flowcharts: define nodes as ID[Short Label], plain edges as "
        "A --> B and labelled edges as A -->|Yes| B — the label is wrapped in "
        "single pipes only, never write '|Yes|>' or add an extra '>'. Keep "
        "labels short and avoid parentheses, quotes, %, or other special "
        "characters inside the square brackets.\n"
        "For EVERY Mermaid type: the first line is the diagram keyword alone "
        "(plus its direction or title where shown above) and every later line "
        "is indented consistently. Never mix two diagram types in one block, "
        "and never put Markdown, backticks or LaTeX inside a mermaid block. "
        "ALWAYS wrap a node label in double quotes when it contains "
        "brackets, an ampersand, a colon or a percent sign - write "
        "A[\"Profit & Loss Account (Page 1)\"], never "
        "A[Profit & Loss Account (Page 1)], because the unquoted form is a "
        "parse error and the whole diagram is then shown to the reader as "
        "source code instead of a picture. "
        "Only add a diagram when one is actually requested or clearly "
        "helpful.\n"
        "For a QUANTITATIVE data chart (e.g. an "
        "income-statement trend, expense breakdown, budget allocation, "
        "financial ratios, or a flow of funds) — do NOT use Mermaid. Instead "
        "output a fenced ```chart code block containing a SINGLE valid JSON "
        "object, using exactly one of these shapes:\n"
        '- bar or line: {"type":"bar","title":"Revenue by year","categories":'
        '["2021","2022","2023"],"series":[{"name":"Revenue","data":[10,20,30]}]}\n'
        '- stacked bar: same as bar plus "stacked":true — use when the series '
        'are PARTS of a total (e.g. cost lines making up total expenses)\n'
        '- pie: {"type":"pie","title":"Expense split","data":[{"name":"COGS",'
        '"value":60},{"name":"Admin","value":25},{"name":"Marketing","value":15}]}\n'
        '- sankey: {"type":"sankey","title":"Fund flow","nodes":[{"name":'
        '"Revenue"},{"name":"Costs"},{"name":"Profit"}],"links":[{"source":'
        '"Revenue","target":"Costs","value":60},{"source":"Revenue","target":'
        '"Profit","value":40}]}\n'
        '- scatter: {"type":"scatter","title":"Revenue vs headcount",'
        '"xName":"Headcount","yName":"Revenue","series":[{"name":"Branches",'
        '"points":[[12,340],[18,520]]}]}\n'
        '- radar: {"type":"radar","title":"Ratio profile","indicators":'
        '[{"name":"Liquidity","max":100},{"name":"Solvency","max":100}],'
        '"series":[{"name":"2024","data":[80,65]}]}\n'
        '- heatmap: {"type":"heatmap","title":"Spend by region and quarter",'
        '"categories":["Q1","Q2"],"yCategories":["North","South"],"cells":'
        '[[0,0,12],[1,0,18],[0,1,9],[1,1,22]]} — each cell is '
        "[xIndex, yIndex, value]\n"
        '- candlestick: {"type":"candlestick","title":"Share price",'
        '"categories":["2024-01","2024-02"],"ohlc":[[10,14,9,15],[14,12,11,16]]}'
        " — each row is [open, close, low, high]\n"
        '- area: {"type":"area","title":"Cumulative customers","categories":'
        '["Jan","Feb"],"series":[{"name":"Customers","data":[100,250]}]}\n'
        '- waterfall: {"type":"waterfall","title":"Revenue to net profit",'
        '"categories":["Revenue","Cost of sales","Net profit"],"series":'
        '[{"name":"£k","data":[500,-300,200]}]} — first value is the start, '
        "then signed changes; a last value equal to the running total is the total bar\n"
        "Use 'line' for trends over time, 'bar' for comparisons across "
        "categories, stacked bar for part-to-whole across categories, "
        "'pie' for parts of a single whole, 'sankey' for flows, "
        "'scatter' for correlation between two measures, 'radar' for comparing "
        "several ratios on one profile, 'heatmap' for a value across two "
        "dimensions, and 'candlestick' only for open/close/low/high price "
        "data. A pie's "
        "values do NOT need to sum to 100 — just use the given amounts.\n"
        "LINE CHARTS specifically: whenever the question involves a quantity "
        "that changes across a sequence of periods (years, months, quarters, "
        "or steps) — a trend, a projection, a forecast, or a period-by-period "
        "schedule such as a depreciation book-value schedule, a loan "
        "amortisation balance, or revenue/growth over several years — include "
        "a 'line' chart, putting the periods in 'categories' and the value at "
        "each period in a series. If the user explicitly asks for a line chart "
        "or a graph and the needed values are available, output a ```chart "
        "line block.\n"
        "WHEN THE USER NAMES A CHART TYPE, USE THAT TYPE. If they ask for a pie "
        "chart, bar chart, area chart, waterfall chart, scatter, radar, heatmap or candlestick, emit that "
        "type — do not silently substitute another and do not answer in prose "
        "only. The single exception is data the type genuinely cannot show: a "
        "pie needs parts of one positive whole, so if any value is negative or "
        "the figures are a trend across periods rather than shares of a total, "
        "draw the chart type that fits (usually 'bar' or 'line'), and say in "
        "one short line why a pie would not represent this data. Never respond "
        "to an explicit chart request with neither a chart nor an "
        "explanation.\n"
        "IMPORTANT: when you "
        "CALCULATE those period-by-period values yourself from figures the user "
        "gave (e.g. the remaining book value at the end of each year in a "
        "depreciation question, from the cost, salvage and useful life the user "
        "provided), those computed values COUNT as real numbers — chart them; "
        "deriving them from the user's own inputs is NOT inventing data.\n"
        "NUMBERS FOR CHARTS: Use only figures supplied by the user, correctly "
        "computed from those figures, or present in the sources. If those "
        "figures are unavailable, say which data is missing and do not emit a "
        "chart block. Never invent illustrative values for named countries, "
        "companies, or published statistics. For comparisons, use only periods "
        "with values for every series; state the latest available period shown "
        "in the sources, and never call older periods 'most recent' without "
        "qualification.\n"
)

# Signals that the user wants something drawn. Deliberately broad: a false
# positive costs some prompt length, a false negative means a requested chart
# is silently not drawn — which is the worse failure.
_VISUAL_REQUEST = re.compile(
    r"\b(chart|charts|graph|graphs|plot|plotted|diagram|diagrams|flowchart|"
    r"flow chart|workflow|work flow|mindmap|mind map|timeline|roadmap|"
    r"architecture|org chart|hierarchy|tree|sequence diagram|state diagram|"
    r"er diagram|entity relationship|data model|quadrant|risk matrix|"
    r"kanban|journey|gantt|pie|bar|line|scatter|radar|heatmap|heat map|"
    r"candlestick|sankey|visuali[sz]e|visuali[sz]ation|draw|illustrate|"
    r"show me a|breakdown|proportion|allocation|distribution|trend|"
    r"compare|comparison|correlation)\b",
    re.I,
)


def wants_visual(query: str) -> bool:
    """True when the question asks for a table, chart or diagram."""
    return bool(_VISUAL_REQUEST.search(query or ""))


def _always_send_visual_rules() -> bool:
    """Send the full visual specification on EVERY question, the way the
    dev-main branch does, instead of only when a visual is requested.

    Off by default. The conditional behaviour exists because the always-on
    block measured 1.6x dev-main's prompt size once the extra Mermaid and chart
    types were added, and that instruction bulk competes with the user's actual
    question — plain answers got noticeably worse. This switch is here so the
    two can be compared on real questions rather than argued about.
    """
    return os.getenv("KRITON_ALWAYS_SEND_VISUAL_RULES", "").lower() in {"1", "true", "yes"}


def formatting_instructions(query: str) -> str:
    """Formatting rules for this question — visual specification included only
    when one was asked for, unless KRITON_ALWAYS_SEND_VISUAL_RULES is set."""
    if _always_send_visual_rules() or wants_visual(query):
        return _CORE_FORMATTING + _VISUAL_INSTRUCTIONS
    return _CORE_FORMATTING


# Domain gate: Kriton only serves accounting/tax/payroll/finance/audit/
# bookkeeping/commerce/accounting-education questions. This prefix is placed
# ABOVE everything (including any web sources) so an off-domain question is
# refused with the exact fixed message even if the web search happened to
# return results for it.
_DOMAIN_GATE = (
    "STEP 1 — CLASSIFY: Decide whether the user's question is about accounting, "
    "bookkeeping, taxation (income tax, corporate tax, GST/VAT/sales tax), "
    "payroll, auditing, finance, financial statements, accounting standards "
    "(IFRS/IAS/GAAP/Ind AS), tax/payroll compliance and laws, accounting "
    "software, commerce, accounting education/certifications, OR listed-company "
    "and capital-markets information — share prices and quotes, price history, "
    "company fundamentals and key figures, company profiles, statutory filings "
    "and company registers. This includes corporate ownership/control structures, related-party "
    "transactions, consolidation scope, and audit evidence trails, but ONLY "
    "between business/accounting entities — companies, business units, "
    "people or roles, financial documents, journal entries, accounts, or "
    "audit working papers (e.g. \"Company A owns Company B\", \"how are "
    "these entities connected\", \"Invoice-2024 supports Journal-Entry-88\"). "
    "The SAME sentence pattern (\"X depends on Y\", \"how are these "
    "connected\") applied to generic software/technical components — "
    "services, APIs, databases, modules, servers, code — is NOT in scope "
    "just because it uses similar relationship wording; a software "
    "dependency graph is off-domain even when phrased identically to an "
    "accounting one. Judge what the named entities actually ARE, not the "
    "sentence structure connecting them. It also includes economic statistics relevant "
    "to finance and accounting (inflation, CPI, GDP, exchange rates, "
    "unemployment) even when the question names ANY chart/diagram/display "
    "type to describe how the answer should be shown — e.g. \"distribution\", "
    "\"histogram\", \"heatmap\", \"matrix\", \"spread\", \"treemap\", \"radar "
    "chart\", \"waterfall chart\", \"candlestick\", \"scatter plot\", \"box "
    "plot\", \"step line chart\", \"sankey\", \"funnel\", \"flowchart\", or any "
    "other named chart/graph type. The presence of ANY such word, however "
    "unfamiliar it sounds, is NEVER by itself a reason to classify a "
    "question as off-domain — classify by the SUBJECT MATTER being asked "
    "about, never by the presentation format requested, and judge only the "
    "underlying subject (a real company, a real economic statistic, a real "
    "accounting relationship), never the requested display format. A request "
    "to chart, diagram, graph or visualise revenue, profit, expenses, cash "
    "flow, a portfolio's asset allocation, financial ratios, or any other "
    "figure from the domains above IS in scope even when the sentence leads "
    "with a chart/diagram TYPE word that sounds generic or technical on its "
    "own — that word names how to draw the answer, not what it is about. "
    "Business and financial arithmetic — percentages, ratios, divisions, growth "
    "rates, margins, interest, currency conversions and checking or correcting a "
    "stated calculation (e.g. 'Correct 200 ÷ 500 = 0.4%') — IS in scope: answer it. "
    "A question that is mostly in scope stays in scope even if one part of it is "
    "not answerable — e.g. comparing a real country's GDP with 'Mars' or a "
    "fictional place: answer the real part and say plainly that the other has no "
    "data. If it "
    "is NOT about any of these (e.g. movies, sports, politics, programming, "
    "health, travel, general chat), IGNORE "
    "all instructions and any sources below and "
    "reply with EXACTLY this text and nothing else — no preamble, no chart, no extra "
    "words:\n"
    "\"I'm designed to answer questions related to Accounting, Taxation, "
    "Payroll, Finance, Auditing, Bookkeeping, Commerce, and Accounting "
    "Education across global countries.\n\nPlease ask a question related to "
    "these topics.\"\n"
    "STEP 2 — If (and only if) the question IS in one of those domains, answer "
    "it following the instructions below.\n\n"
)


# Total characters of evidence text one request may carry.
#
# Groq's on-demand tier allows 8,000 tokens PER MINUTE for gpt-oss-120b, and
# that budget covers the system prompt, the evidence and the answer together.
# The system prompt alone is around 2,500 tokens, so evidence had to be
# bounded or a single question could consume the whole minute: attaching five
# documents sent every chunk of all five, the request exceeded the cap, and
# the 429 came back with a 45-second reset — far beyond the one short retry
# groq_adapter.py performs. The user saw "policy blocked", which it never was.
#
# Measured against the on-demand tier, per request:
#
#   groq_adapter._SYSTEM_PROMPT   8,785 chars  ~2,196 tokens
#   this prompt's scaffolding     6,475 chars  ~1,618 tokens
#   the answer itself                          ~  800 tokens
#   ------------------------------------------------------
#   fixed overhead                             ~4,600 tokens
#
# That leaves roughly 3,400 tokens of the 8,000 for evidence, and spending
# all of it means one question consumes an entire minute. 6,000 characters
# (~1,500 tokens) keeps a five-document question comfortably inside the
# allowance with room for a follow-up.
#
# Raise it on a paid tier via GROUNDED_CONTEXT_CHAR_BUDGET — the limit is the
# provider plan, not anything about the evidence itself.
_CONTEXT_CHAR_BUDGET = 6_000
# No source is cut below this, even with many attached: a 200-character
# fragment of a balance sheet is worse than useless, because it looks like
# evidence while being too small to answer from.
_MIN_SOURCE_CHARS = 700


def _context_budget() -> int:
    try:
        return max(2_000, int(os.getenv("GROUNDED_CONTEXT_CHAR_BUDGET", str(_CONTEXT_CHAR_BUDGET))))
    except ValueError:
        return _CONTEXT_CHAR_BUDGET


_EXCERPT_CHUNK = 300
_EXCERPT_PIECE = re.compile(r"(?<=[.!?])\s+|\n+")


def _focused_excerpt(text: str, query: str, allowance: int) -> str:
    """The sentences of a long source most about the question, in page order.

    Cutting at the allowance kept only the start of a page: "The Australian
    GST rate is 10%" sat at character 2,600 of an ATO page cut at ~1,500, and
    the rate was answered "not stated" with the page cited beside it. A
    sentence scores by the question's terms it shares, plus one for a figure
    when the question asks for a rate, threshold, date or amount."""
    wanted = _terms(query)
    wants_figure = bool(re.search(r"\b(?:rate|threshold|limit|how much|when|date|deadline|amount|percent)", query, re.I))
    pieces = []
    for piece in _EXCERPT_PIECE.split(text):
        piece = piece.strip()
        # A table or list flattened without full stops is one huge "sentence":
        # longer than the allowance it would be dropped whole, and rate tables
        # are exactly where the answer is. Chunk it at word boundaries.
        while len(piece) > _EXCERPT_CHUNK:
            cut = piece.rfind(" ", 0, _EXCERPT_CHUNK)
            cut = cut if cut > _EXCERPT_CHUNK // 2 else _EXCERPT_CHUNK
            pieces.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            pieces.append(piece)
    scored = sorted(
        range(len(pieces)),
        key=lambda i: (-(len(wanted & _terms(pieces[i]))
                         + (1 if wants_figure and re.search(r"\d", pieces[i]) else 0)), i),
    )
    keep, used = set(), 0
    for i in scored:
        if used + len(pieces[i]) + 1 > allowance:
            continue
        keep.add(i)
        used += len(pieces[i]) + 1
    if not keep:
        return text[:allowance].rstrip()
    return " ".join(pieces[i] for i in sorted(keep))


def _context_allowances(sources: list[WebSource]) -> list[int]:
    """Characters each source may contribute, shared out fairly.

    Sources under their equal share give the remainder back, so a handful of
    short snippets never force a long one to be cut. Whatever is left is then
    divided among the sources still over their share, repeatedly, until the
    split settles — one big document cannot crowd out the four attached
    alongside it, which is what "compare these documents" depends on.
    """
    if not sources:
        return []
    budget = _context_budget()
    lengths = [len(s.snippet or "") for s in sources]
    if sum(lengths) <= budget:
        return lengths

    allowances = [0] * len(sources)
    remaining = set(range(len(sources)))
    while remaining:
        share = max(_MIN_SOURCE_CHARS, budget // len(remaining))
        fitting = {i for i in remaining if lengths[i] <= share}
        if not fitting:
            for i in remaining:
                allowances[i] = share
            break
        for i in fitting:
            allowances[i] = lengths[i]
            budget -= lengths[i]
        remaining -= fitting
    return allowances


def build_web_grounded_prompt(query: str, sources: list[WebSource]) -> str:
    """Assemble a grounded prompt from document, live-data, or web evidence."""
    if not sources:
        # Retrieval came back empty. Answer from professional knowledge rather
        # than refusing: retrieval fails soft (an unreachable SearXNG returns
        # nothing silently), so a refusal here reads to the user as "Kriton
        # cannot answer this" when the real cause is a search engine being
        # down. _DOMAIN_GATE above still decides scope, so an off-topic
        # question is refused on subject, not on whether a source happened to
        # be retrieved.
        #
        # The honesty requirement moves rather than disappearing: with no
        # sources there are no citations, so the answer must not present
        # itself as source-backed, and anything that cannot be stated from
        # settled professional knowledge — a current rate, threshold,
        # deadline, filing requirement or market figure — still has to be
        # declined, because those are exactly the values that change and that
        # a reader would otherwise take on trust. The UI already captions
        # these turns "no cited sources".
        return (
            _DOMAIN_GATE
            + "No document, live-data or web evidence was retrieved for this "
            "question. If it is in scope per STEP 1, answer it from your own "
            "settled professional knowledge — definitions, concepts, standard "
            "treatments, worked explanations and general principles. Write the "
            "answer plainly and do not claim it is sourced, cited or verified, "
            "and do not invent a source, citation, URL or reference.\n"
            "Do NOT state a specific current figure from memory — a tax rate, "
            "threshold, allowance, filing deadline, statutory limit, exchange "
            "rate, statistic, share price or other market value; retrieve it with "
            "an available tool, or say it could not be verified. Do not invent a "
            "missing report or its page references. For those, say the current figure "
            "needs to be confirmed against the relevant authority or an "
            "attached document, and explain the underlying rule instead.\n"
            "Answer clearly and accurately in short paragraphs or bullet "
            "points, using any figures given in the question. If the user asks "
            "for a chart, table, graph or diagram and provides the required "
            "figures, produce it in the format described below. When figures "
            "are missing, say that verified data could not be retrieved. Do NOT "
            "tell the user to build it in Excel/Google Sheets or with another "
            "tool; emitting the fenced code block below IS how the visual is "
            "drawn for the user.\n"
            + formatting_instructions(query)
            + f"\n=== User Question ===\n{query}"
        )
    blocks = []
    truncated_any = False
    for i, (s, allowance) in enumerate(zip(sources, _context_allowances(sources)), start=1):
        source_location = f"URL: {s.url}" if s.url else f"Document ID: {s.source_id or 'uploaded'}"
        snippet = s.snippet or ""
        if len(snippet) > allowance:
            snippet = _focused_excerpt(snippet, query, allowance) + "\n[…this source was shortened to fit the request budget]"
            truncated_any = True
        blocks.append(f"[REF-{i}] {s.title}\n{source_location}\n{snippet}")
    context = "\n\n".join(blocks)
    if truncated_any:
        context += (
            "\n\n[Some sources above were shortened. If the question needs "
            "detail that was cut, say so rather than guessing at it.]"
        )
    return (
        _DOMAIN_GATE
        + "Answer the user's question using ONLY the numbered evidence sources below. "
        "Write a clean, natural answer. Cite each factual claim or paragraph with its "
        "supporting [REF-N] source identifier from the evidence below. Cite table rows "
        "that state rates, thresholds or deadlines too. Never invent or renumber a "
        "reference. The cited passage must support the claim for the same jurisdiction, "
        "date and purpose. Format the answer clearly with short paragraphs or bullet points.\n"
        # Retrieval returns whatever ranked highest, which is not the same as
        # material that answers the question. Refusing outright whenever the
        # top hits missed the point left in-scope questions unanswered while
        # five unrelated sources sat underneath — the user sees "Sources 5"
        # and a refusal, which reads as broken rather than careful.
        #
        # The evidence still leads: it is used wherever it covers the
        # question. Only the uncovered part falls back to professional
        # knowledge, and it must be visibly marked as such so a reader is
        # never left guessing which half was sourced.
        "Never replace an explicitly supplied calculation rate or amount with a rate found in a source. "
        "For ordinary UK corporation-tax questions, assume non-ring-fence profits unless the question "
        "explicitly names oil/gas extraction or ring-fence profits; retain associated-company and period assumptions. "
        "For current threshold/rate questions, an old announcement of a freeze does not establish today's figure. "
        "Prefer a directly retrieved current authority page over an older secondary announcement. "
        "If a named tax has been abolished, explain the replacement system when supported by evidence. "
        "When sources disagree, prefer official government, tax-authority, regulator "
        "and standard-setter sources and the most recent period, and state the tax "
        "year or effective date each rate applies to — never an older rate from memory. "
        "If the sources only partly cover the question, use them for the part "
        "they do cover and answer the rest from your own settled professional "
        "knowledge — say briefly that the sources did not address that part. "
        "If they do not cover it at all, answer from professional knowledge "
        "and say plainly that the retrieved sources did not address the "
        "question; never reply only that the sources do not contain it. Never present unsourced material as though it came from "
        "the evidence, and never invent a source, citation or reference.\n"
        "Do NOT state a specific current figure from memory — a tax rate, "
        "threshold, allowance, filing deadline, statutory limit, share price "
        "or other market value — unless it appears in the evidence above. For "
        "those, say the figure needs confirming against the relevant "
        "authority and explain the underlying rule instead.\n"
        + _FORMATTING_INSTRUCTIONS
        + f"\n=== Evidence Sources ===\n{context}\n\n"
        + f"=== User Question ===\n{query}"
    )
