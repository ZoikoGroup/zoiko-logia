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


def build_web_grounded_prompt(query: str, sources: list[WebSource]) -> str:
    """Assemble the grounded instruction: the LLM must answer only from these
    numbered web sources and cite them as [REF-N]. This is what produces the
    clean, structured, cited answer format."""
    if not sources:
        return query
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[REF-{i}] {s.title}\nURL: {s.url}\n{s.snippet}")
    context = "\n\n".join(blocks)
    return (
        "Answer the user's question using ONLY the numbered web sources below. "
        "Write a clean, natural answer. Do NOT insert citation markers such as "
        "[REF-1], [1], or source numbers anywhere in the answer text — the "
        "sources are shown to the reader separately below, so the answer must "
        "read cleanly without them. If the sources do not contain the answer, "
        "say so plainly instead of guessing. Format the answer clearly with "
        "short paragraphs or bullet points where helpful.\n"
        "When the user asks for a table, a comparison, 'tabular format', or the "
        "content is naturally a comparison of two or more items across "
        "attributes, present it as a GitHub-flavoured Markdown table using pipe "
        "syntax — a header row like '| Attribute | Option A | Option B |', then "
        "a separator row '| --- | --- | --- |', then one row per attribute. Keep "
        "cell text concise.\n"
        "If the user asks for a flowchart, architecture, workflow, decision "
        "tree, sequence, state, or any other diagram, include it as a Mermaid "
        "diagram inside a fenced ```mermaid code block, alongside a short text "
        "explanation. Choose the Mermaid diagram type that best fits: "
        "'flowchart TD' (or 'flowchart LR') for processes, workflows, "
        "architecture and decision trees; 'sequenceDiagram' for step-by-step "
        "interactions between parties; 'stateDiagram-v2' for states and "
        "transitions. For flowcharts, define nodes as ID[Short Label], plain "
        "edges as A --> B and labelled edges as A -->|Yes| B — the label is "
        "wrapped in single pipes only, never write '|Yes|>' or add an extra "
        "'>'. Keep labels short and avoid parentheses, quotes, %, or other "
        "special characters inside the square brackets. Only add a diagram "
        "when one is actually requested or clearly helpful.\n\n"
        f"=== Web Sources ===\n{context}\n\n"
        f"=== User Question ===\n{query}"
    )
