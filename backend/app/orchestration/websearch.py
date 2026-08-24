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

import os
from dataclasses import dataclass

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
    (fail-soft)."""
    base = _searxng_url()
    # Topic narrows the allowlist from "every body in this jurisdiction" to
    # the ones with authority over THIS question (source_taxonomy.py). An
    # off-taxonomy question detects no topics, which yields the full
    # jurisdiction list — the behaviour before topics existed.
    domains = allowed_domains(jurisdiction, detect_topics(query))
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
        return _spread_across_organisations(trusted, domains, limit)
    if _strict_allowlist():
        return []
    # Fallback: no trusted-domain hits — return the general top results so the
    # bot still answers (allowlist is advisory unless SEARXNG_STRICT_ALLOWLIST).
    # Spread these too: organisation_key falls back to the bare hostname off
    # the allowlist, so five pages of one blog still collapse to one voice.
    return _spread_across_organisations(parsed, domains, limit)


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


def build_web_grounded_prompt(query: str, sources: list[WebSource]) -> str:
    """Assemble a grounded prompt from document, live-data, or web evidence."""
    if not sources:
        return (
            _DOMAIN_GATE
            + "No reliable document, live-data, or web evidence was retrieved. "
            "Do not answer from model knowledge and do not invent facts. State "
            "briefly that reliable evidence could not be retrieved and ask the "
            "user to attach a readable document or clarify the source scope.\n"
            + _FORMATTING_INSTRUCTIONS
            + f"\n=== User Question ===\n{query}"
        )
    blocks = []
    for i, s in enumerate(sources, start=1):
        source_location = f"URL: {s.url}" if s.url else f"Document ID: {s.source_id or 'uploaded'}"
        blocks.append(f"[REF-{i}] {s.title}\n{source_location}\n{s.snippet}")
    context = "\n\n".join(blocks)
    return (
        _DOMAIN_GATE
        + "Answer the user's question using ONLY the numbered evidence sources below. "
        "Write a clean, natural answer. Do NOT insert citation markers such as "
        "[REF-1], [1], or source numbers anywhere in the answer text — the "
        "sources are shown to the reader separately below, so the answer must "
        "read cleanly without them. If the sources do not contain the answer, "
        "say so plainly instead of guessing. Format the answer clearly with "
        "short paragraphs or bullet points where helpful.\n"
        + _FORMATTING_INSTRUCTIONS
        + f"\n=== Evidence Sources ===\n{context}\n\n"
        + f"=== User Question ===\n{query}"
    )
