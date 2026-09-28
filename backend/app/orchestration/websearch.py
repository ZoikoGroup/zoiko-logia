"""
SearXNG web-search retrieval layer for Ask Kriton™.

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
import os
from dataclasses import asdict, dataclass

import httpx

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


def _searxng_url() -> str:
    return os.getenv("SEARXNG_URL", "http://localhost:8888").rstrip("/")


def _strict_allowlist() -> bool:
    return os.getenv("SEARXNG_STRICT_ALLOWLIST", "").lower() in {"1", "true", "yes"}


# ── Result cache ────────────────────────────────────────────────────────────
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
_CACHE_KEY_PREFIX = "websearch:v1:"

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


async def web_search(query: str, jurisdiction: str = "", limit: int = 5) -> list[WebSource]:
    """Query SearXNG and return up to `limit` sources, preferring trusted
    domains for the jurisdiction and topic. Returns [] on any failure
    (fail-soft).

    Successful results are cached in Redis for SEARXNG_CACHE_TTL_SECONDS so a
    repeated question does not make a second trip to the upstream engines —
    see the cache block above for why that matters more than the latency it
    saves. An unreachable cache degrades to a normal search.
    """
    cache_key = _cache_key(query, jurisdiction, limit)
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

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
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(f"{base}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = data.get("results", []) or []

    # Normalise into WebSource, keeping only entries with a usable URL.
    parsed: list[WebSource] = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        parsed.append(
            WebSource(
                title=(r.get("title") or url)[:200],
                url=url,
                snippet=(r.get("content") or "").strip(),
            )
        )

    trusted = [s for s in parsed if matches_allowlist(s.url, domains)]

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
    await _cache_put(cache_key, selected)
    return selected


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
    "Return only the user-facing answer. Never print internal routing labels "
    "such as 'CLASSIFICATION:', 'CLASSIFIED:', or 'ANSWER:'. Start directly "
    "with the answer content. Do not use double-asterisk Markdown emphasis; "
    "use plain text or Markdown headings instead.\n"
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
        "For mathematical formulas, methods and calculations, use LaTeX so they "
        "render cleanly: wrap an INLINE formula or value in single dollar signs "
        "$...$ (e.g. $Depreciation = (Cost - Salvage) / Life$), and put a "
        "standalone/display equation on its own line wrapped in double dollar "
        "signs $$...$$. Do NOT wrap an inline value in $$...$$. Show the "
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
    "plot\", \"step line chart\", or any other named chart/graph type. The "
    "presence of ANY such word, however unfamiliar it sounds, is NEVER by "
    "itself a reason to classify a question as off-domain — judge only the "
    "underlying subject (a real company, a real economic statistic, a real "
    "accounting relationship), never the requested display format. If it "
    "is NOT about any of these (e.g. movies, sports, politics, programming, "
    "health, travel, general chat), IGNORE "
    "all instructions and any sources below and "
    "reply with EXACTLY this text and nothing else — no preamble, no extra "
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
            "threshold, allowance, filing deadline, statutory limit, share "
            "price or other market value. For those, say the current figure "
            "needs to be confirmed against the relevant authority or an "
            "attached document, and explain the underlying rule instead.\n"
            + _FORMATTING_INSTRUCTIONS
            + f"\n=== User Question ===\n{query}"
        )
    blocks = []
    truncated_any = False
    for i, (s, allowance) in enumerate(zip(sources, _context_allowances(sources)), start=1):
        source_location = f"URL: {s.url}" if s.url else f"Document ID: {s.source_id or 'uploaded'}"
        snippet = s.snippet or ""
        if len(snippet) > allowance:
            snippet = snippet[:allowance].rstrip() + "\n[…this source was shortened to fit the request budget]"
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
        "Write a clean, natural answer. Do NOT insert citation markers such as "
        "[REF-1], [1], or source numbers anywhere in the answer text — the "
        "sources are shown to the reader separately below, so the answer must "
        "read cleanly without them. Format the answer clearly with short "
        "paragraphs or bullet points where helpful.\n"
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
        "If the sources only partly cover the question, use them for the part "
        "they do cover and answer the rest from your own settled professional "
        "knowledge — say briefly that the sources did not address that part. "
        "If they do not cover it at all, answer from professional knowledge "
        "and say plainly that the retrieved sources did not address the "
        "question. Never present unsourced material as though it came from "
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
