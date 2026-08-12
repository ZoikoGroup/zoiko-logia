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


# Trusted, authoritative domains per jurisdiction. Results outside these are
# dropped when an allowlist applies (see resolve). "GLOBAL" always applies.
_TRUSTED_DOMAINS: dict[str, list[str]] = {
    "GLOBAL": ["ifrs.org", "iasb.org", "ifac.org", "iaasb.org"],
    "UK": ["gov.uk", "hmrc.gov.uk", "frc.org.uk", "icaew.com", "accaglobal.com", "legislation.gov.uk"],
    "US": ["irs.gov", "fasb.org", "sec.gov", "pcaobus.org", "aicpa.org", "gao.gov"],
    "EU": ["europa.eu", "efrag.org"],
    "UAE": ["mof.gov.ae", "tax.gov.ae"],
    "INDIA": ["incometax.gov.in", "icai.org", "mca.gov.in"],
}


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
    freshness: str | None = None      # realtime | delayed | historical | filing


def _searxng_url() -> str:
    return os.getenv("SEARXNG_URL", "http://localhost:8888").rstrip("/")


def _strict_allowlist() -> bool:
    return os.getenv("SEARXNG_STRICT_ALLOWLIST", "").lower() in {"1", "true", "yes"}


def _allowed_domains(jurisdiction: str) -> list[str]:
    key = (jurisdiction or "").upper().split("-")[0]  # "US-CA" -> "US"
    domains = list(_TRUSTED_DOMAINS.get("GLOBAL", []))
    if key in _TRUSTED_DOMAINS:
        domains += _TRUSTED_DOMAINS[key]
    return domains


def _matches_allowlist(url: str, domains: list[str]) -> bool:
    return any(d in url for d in domains)


async def web_search(query: str, jurisdiction: str = "", limit: int = 5) -> list[WebSource]:
    """Query SearXNG and return up to `limit` sources, preferring trusted
    domains for the jurisdiction. Returns [] on any failure (fail-soft)."""
    base = _searxng_url()
    params = {
        "q": query,
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

    domains = _allowed_domains(jurisdiction)
    trusted = [s for s in parsed if _matches_allowlist(s.url, domains)]

    if trusted:
        return trusted[:limit]
    if _strict_allowlist():
        return []
    # Fallback: no trusted-domain hits — return the general top results so the
    # bot still answers (allowlist is advisory unless SEARXNG_STRICT_ALLOWLIST).
    return parsed[:limit]


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
        "When the user requests a chart, graph, heatmap, flowchart, workflow, "
        "distribution, histogram, box plot, spread, or other visualization of "
        "a real numeric data series, a separate validated renderer handles "
        "it. Do not substitute a markdown data table, recommend third-party "
        "drawing tools, describe a hypothetical image, invent "
        "values/relationships, or re-list every individual data point "
        "yourself — give only a concise 1-2 sentence interpretation of the "
        "supplied evidence (e.g. the overall range or direction), not a full "
        "restatement of it.\n"
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
    "unemployment) even when the question uses a statistical/technical term "
    "like \"distribution\", \"histogram\", \"heatmap\", \"matrix\", or "
    "\"spread\" to describe how the answer should be shown — the presence of "
    "that word alone is NEVER a reason to classify a question as off-domain; "
    "judge the underlying subject, not the requested display format. If it "
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
    """Assemble the answering prompt. When web sources were found, the model is
    told to ground its answer in them (cited separately in the UI). When none
    were found, it answers from its own knowledge, but EITHER way the
    table/formula formatting rules apply. An off-domain question is refused up
    front via _DOMAIN_GATE. Charts/diagrams are NOT requested here — see
    _FORMATTING_INSTRUCTIONS' docstring for why that moved to a separate,
    evidence-backed pipeline instead of free-text LLM authorship."""
    if not sources:
        return (
            _DOMAIN_GATE
            + "Answer the user's question clearly and accurately using your own "
            "professional knowledge and any figures given in the question. Use "
            "short paragraphs or bullet points.\n"
            + _FORMATTING_INSTRUCTIONS
            + f"\n=== User Question ===\n{query}"
        )
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[REF-{i}] {s.title}\nURL: {s.url}\n{s.snippet}")
    context = "\n\n".join(blocks)
    return (
        _DOMAIN_GATE
        + "Answer the user's question using ONLY the numbered web sources below. "
        "Write a clean, natural answer. Do NOT insert citation markers such as "
        "[REF-1], [1], or source numbers anywhere in the answer text — the "
        "sources are shown to the reader separately below, so the answer must "
        "read cleanly without them. If the sources do not contain the answer, "
        "say so plainly instead of guessing. Format the answer clearly with "
        "short paragraphs or bullet points where helpful.\n"
        + _FORMATTING_INSTRUCTIONS
        + f"\n=== Web Sources ===\n{context}\n\n"
        + f"=== User Question ===\n{query}"
    )
