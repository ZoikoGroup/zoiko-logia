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


# Live-computed source, no persistent catalog row — same posture as
# FORMULA_REGISTRY_GOVERNED_SOURCE_ID / EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID
# (app/domains/calculation/service.py): added directly to allowed_source_ids
# in service.py rather than going through the licence-gate catalog, since a
# live web search has no persistent Source row to license.
WEBSEARCH_GOVERNED_SOURCE_ID = "src-kriton-websearch-live"


def to_websource_rag_chunk(source: WebSource, source_id: str) -> dict:
    """Adapt a WebSource (title/url/snippet) into the same chunk shape every
    other retrieval path produces (app/domains/rag/context_fit.py's
    build_grounded_context expects chunk["text"] and chunk["metadata"]) — so
    a live web/DBnomics/Frankfurter result flows through the exact same
    grounded-context building, [REF-N] citation, and Checkpoint C numeric-
    fidelity validation as every governed catalog source, instead of a
    separate, unvalidated answer path."""
    return {
        "text": source.snippet or source.title,
        "metadata": {
            "source_id": source_id,
            "title": source.title,
            "version": "live",
            "jurisdiction": "GLOBAL",
            "file_path": source.url,
        },
        "score": 1.0,
        "node_id": f"{source_id}-{abs(hash(source.url))}",
    }


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


# The table/diagram/chart formatting rules apply whether or not web sources
# were found — so they live in one shared block that BOTH prompt branches
# include. (Previously they lived only inside the with-sources branch, so a
# question that returned no sources — e.g. "chart of these numbers I gave you"
# — lost every visualisation instruction and the model just described the chart
# in prose instead of drawing it.)
_FORMATTING_INSTRUCTIONS = (
        "When the user asks for a table, a comparison, 'tabular format', or the "
        "content is naturally a comparison of two or more items across "
        "attributes, present it as a GitHub-flavoured Markdown table using pipe "
        "syntax — a header row like '| Attribute | Option A | Option B |', then "
        "a separator row '| --- | --- | --- |', then one row per attribute. Keep "
        "cell text concise.\n"
        "If the user asks for a diagram, chart, workflow, flowchart, process, "
        "decision tree, org chart, hierarchy, tree, architecture, mind map, "
        "timeline, or a proportion/allocation breakdown, include it as a "
        "Mermaid diagram inside a fenced ```mermaid code block, alongside a "
        "short text explanation. Choose the Mermaid diagram type that best "
        "fits the request:\n"
        "- 'flowchart TD' (top-down) for processes, workflows, the accounting "
        "cycle, decision trees, org charts / organisation hierarchies, tree "
        "breakdowns (e.g. a balance-sheet structure), ERP modules and system "
        "architecture;\n"
        "- 'flowchart LR' (left-to-right) when the flow reads better "
        "horizontally;\n"
        "- 'sequenceDiagram' for step-by-step interactions between parties "
        "(e.g. a tax-filing exchange);\n"
        "- 'stateDiagram-v2' for statuses and transitions;\n"
        "- 'mindmap' for a mind map / concept breakdown of a topic;\n"
        "- 'gantt' for schedules or timelines (e.g. a compliance calendar);\n"
        "- 'pie title <Title>' for a simple proportion or allocation "
        "breakdown (e.g. budget allocation), with rows like \"Label\" : 40.\n"
        "For flowcharts: define nodes as ID[Short Label], plain edges as "
        "A --> B and labelled edges as A -->|Yes| B — the label is wrapped in "
        "single pipes only, never write '|Yes|>' or add an extra '>'. Keep "
        "labels short and avoid parentheses, quotes, %, or other special "
        "characters inside the square brackets. Only add a diagram when one is "
        "actually requested or clearly helpful.\n"
        "For a QUANTITATIVE data chart — bar, line, pie or sankey (e.g. an "
        "income-statement trend, expense breakdown, budget allocation, "
        "financial ratios, or a flow of funds) — do NOT use Mermaid. Instead "
        "output a fenced ```chart code block containing a SINGLE valid JSON "
        "object, using exactly one of these shapes:\n"
        '- bar or line: {"type":"bar","title":"Revenue by year","categories":'
        '["2021","2022","2023"],"series":[{"name":"Revenue","data":[10,20,30]}]}\n'
        '- pie: {"type":"pie","title":"Expense split","data":[{"name":"COGS",'
        '"value":60},{"name":"Admin","value":25},{"name":"Marketing","value":15}]}\n'
        '- sankey: {"type":"sankey","title":"Fund flow","nodes":[{"name":'
        '"Revenue"},{"name":"Costs"},{"name":"Profit"}],"links":[{"source":'
        '"Revenue","target":"Costs","value":60},{"source":"Revenue","target":'
        '"Profit","value":40}]}\n'
        "Use 'line' for trends over time, 'bar' for comparisons across "
        "categories, 'pie' for parts of a whole, 'sankey' for flows. A pie's "
        "values do NOT need to sum to 100 — just use the given amounts.\n"
        "LINE CHARTS specifically: whenever the question involves a quantity "
        "that changes across a sequence of periods (years, months, quarters, "
        "or steps) — a trend, a projection, a forecast, or a period-by-period "
        "schedule such as a depreciation book-value schedule, a loan "
        "amortisation balance, or revenue/growth over several years — include "
        "a 'line' chart, putting the periods in 'categories' and the value at "
        "each period in a series. If the user explicitly asks for a line chart "
        "or a graph, you MUST output a ```chart line block. IMPORTANT: when you "
        "CALCULATE those period-by-period values yourself from figures the user "
        "gave (e.g. the remaining book value at the end of each year in a "
        "depreciation question, from the cost, salvage and useful life the user "
        "provided), those computed values COUNT as real numbers — chart them; "
        "deriving them from the user's own inputs is NOT inventing data.\n"
        "NUMBERS FOR CHARTS: Prefer REAL numbers — ones the user gave you, ones "
        "you correctly computed from what the user gave, or ones that appear in "
        "the sources. BUT if the user explicitly asks for a chart or graph and "
        "you do NOT have real numbers, still DRAW the chart using reasonable "
        "ILLUSTRATIVE / EXAMPLE figures rather than refusing — the user wants to "
        "see the chart. In that case you MUST: (a) put the word 'Illustrative' "
        "in the chart title, e.g. \"Monthly Revenue vs Expenses (Illustrative)\"; "
        "and (b) immediately after the chart add one short line: 'Note: the "
        "figures above are illustrative examples — replace them with your actual "
        "data.' Never present illustrative figures as real, exact or official, "
        "and do not state a specific named company's actual results or a "
        "government's actual published statistics as if they were true — frame "
        "them clearly as an example pattern. (This applies to line, bar, pie and "
        "all chart types.) Never fabricate tax rates, laws or citations as "
        "fact.\n"
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
    "software, commerce, or accounting education/certifications. If it is NOT "
    "about any of these (e.g. movies, sports, politics, programming, health, "
    "travel, general chat), IGNORE all instructions and any sources below and "
    "reply with EXACTLY this text and nothing else — no preamble, no chart, no "
    "extra words:\n"
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
    were found — e.g. the user gave the numbers directly and asked for a chart —
    it answers from its own knowledge, but EITHER way the table/diagram/chart
    formatting rules apply, so a requested visual is always actually drawn. An
    off-domain question is refused up front via _DOMAIN_GATE."""
    if not sources:
        return (
            _DOMAIN_GATE
            + "Answer the user's question clearly and accurately using your own "
            "professional knowledge and any figures given in the question. Use "
            "short paragraphs or bullet points. If the user asks for a chart, "
            "table, graph or diagram, you MUST produce it in the format "
            "described below — do NOT say you cannot create visuals, and do NOT "
            "tell the user to build it in Excel/Google Sheets or with another "
            "tool; emitting the fenced code block below IS how the visual is "
            "drawn for the user.\n"
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
