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
import re
from dataclasses import dataclass

import httpx

# The authoritative-source allowlist lives in source_taxonomy.py: it is keyed on
# jurisdiction x topic, so a payroll question is matched against payroll bodies
# rather than every domain for the country. See that module for the matrix.
from app.orchestration.source_taxonomy import (
    allowed_domains,
    detect_topics,
    matches_allowlist,
    organisation_key,
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
    freshness: str | None = None      # realtime | delayed | historical | filing


def _searxng_url() -> str:
    return os.getenv("SEARXNG_URL", "http://localhost:8888").rstrip("/")


def _strict_allowlist() -> bool:
    return os.getenv("SEARXNG_STRICT_ALLOWLIST", "").lower() in {"1", "true", "yes"}


def _max_per_organisation() -> int:
    """How many results one organisation may contribute before others get a
    turn. 2 keeps the definitive body well represented without letting it fill
    the whole panel."""
    try:
        return max(1, int(os.getenv("SEARXNG_MAX_PER_ORG", "2")))
    except ValueError:
        return 2


def _spread_across_organisations(
    sources: list[WebSource], domains: list[str], limit: int
) -> list[WebSource]:
    """Pick `limit` sources spread across DIFFERENT bodies rather than taking
    the top N by relevance.

    Relevance order alone returned five gov.uk pages for a VAT question — all
    correct, all one organisation, and no corroboration. Round-robin over
    organisations instead: the most relevant hit from each body first, then the
    second from each, up to SEARXNG_MAX_PER_ORG.

    Relevance is preserved within each organisation, and if too few bodies
    replied to fill `limit` the remainder is topped up in the original order —
    a thin panel is worse than a slightly repetitive one.
    """
    buckets: dict[str, list[WebSource]] = {}
    order: list[str] = []
    for s in sources:
        key = organisation_key(s.url, domains)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(s)

    picked: list[WebSource] = []
    for rank in range(_max_per_organisation()):
        for key in order:
            if len(picked) >= limit:
                return picked
            bucket = buckets[key]
            if len(bucket) > rank:
                picked.append(bucket[rank])

    # Fewer organisations than slots — fill the rest by relevance.
    if len(picked) < limit:
        taken = {id(s) for s in picked}
        for s in sources:
            if id(s) not in taken:
                picked.append(s)
                if len(picked) >= limit:
                    break
    return picked[:limit]


async def _query_searxng(query: str) -> list[WebSource]:
    """One SearXNG call, normalised. Returns [] on any failure (fail-soft)."""
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

    # Keep only entries with a usable URL.
    parsed: list[WebSource] = []
    for r in data.get("results", []) or []:
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
    return parsed


async def web_search(query: str, jurisdiction: str = "", limit: int = 5) -> list[WebSource]:
    """Query SearXNG and return up to `limit` sources from the bodies with
    authority over the question's topic. Returns [] on any failure (fail-soft).

    ONE SearXNG call per question, deliberately. An earlier version ran a second
    `site:`-biased pass to steer the engines toward the authoritative domains.
    It did retrieve better sources, but it doubled the query volume, and the
    public engines behind SearXNG (DuckDuckGo, Brave, Startpage, Google CSE)
    rate-limit and serve CAPTCHAs well before that pays off — the whole panel
    then comes back empty, which is far worse than a slightly weaker source.
    Topic relevance is still applied, just by filtering rather than by asking
    twice.
    """
    topics = detect_topics(query)
    domains = allowed_domains(jurisdiction, topics)

    parsed = await _query_searxng(query)
    if not parsed:
        return []

    trusted = [s for s in parsed if matches_allowlist(s.url, domains)]

    if trusted:
        return _spread_across_organisations(trusted, domains, limit)
    if _strict_allowlist():
        return []
    # Fallback: no trusted-domain hits — return the general top results so the
    # bot still answers (allowlist is advisory unless SEARXNG_STRICT_ALLOWLIST).
    # Spread these too: five pages from one content farm is the worst case.
    return _spread_across_organisations(parsed, domains, limit)


# The table/diagram/chart formatting rules apply whether or not web sources
# were found — so they live in one shared block that BOTH prompt branches
# include. (Previously they lived only inside the with-sources branch, so a
# question that returned no sources — e.g. "chart of these numbers I gave you"
# — lost every visualisation instruction and the model just described the chart
# in prose instead of drawing it.)
# Formatting rules are split in two so the model is not handed the full
# diagram/chart specification on every request.
#
# Measured: bolting the extra Mermaid types and chart schemas onto the shared
# block took the prompt from ~6,000 to ~9,700 characters — 1.6x — on EVERY
# question, including "what is tax". That much instruction competes with the
# actual question for the model's attention and measurably degraded plain
# answers. _VISUAL_INSTRUCTIONS is therefore appended only when the question
# asks for a visual (see wants_visual), which keeps the base prompt smaller
# than it was before the extra types were added, with no loss of capability
# when a chart or diagram IS requested.

# Always sent: cheap, and a table or a formula can be the right shape for any
# answer.
_CORE_FORMATTING = (
        "When the user asks for a table, a comparison, 'tabular format', or the "
        "content is naturally a comparison of two or more items across "
        "attributes, present it as a GitHub-flavoured Markdown table using pipe "
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
        "short text explanation. Choose the Mermaid diagram type that best "
        "fits the request:\n"
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
        "or a graph, you MUST output a ```chart line block.\n"
        "WHEN THE USER NAMES A CHART TYPE, USE THAT TYPE. If they ask for a pie "
        "chart, bar chart, scatter, radar, heatmap or candlestick, emit that "
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
# One retrieved excerpt from a file the user uploaded. Declared here rather
# than imported from app.domains.documents so this module keeps its single
# direction of dependency (orchestration does not reach into domains);
# orchestration/service.py maps the domain type onto this one.
@dataclass
class DocumentExcerpt:
    filename: str
    locator: str
    content: str


# Appended to the domain gate when the user has attached files. Without it the
# gate refuses perfectly legitimate questions: someone who uploads a trial
# balance and asks "what is the total in the closing column" is asking an
# accounting question, but the bare words do not look like one, and refusing it
# while their own document sits in the prompt is the worst possible answer.
_DOCUMENT_SCOPE_NOTE = (
    "SCOPE NOTE: the user has attached one or more of their own documents and "
    "excerpts from them appear below. A question about the content of those "
    "attached documents IS in scope and must be answered from them — including "
    "questions about specific figures, rows, totals, dates, names, clauses or "
    "sections in the file. Do not refuse such a question as off-topic.\n\n"
)

# How uploaded documents are described to the model. The distinction this
# paragraph draws is the whole point of the feature: the user's own file is
# EVIDENCE ABOUT THEIR SITUATION, never AUTHORITY about what the rules are.
# Conflating the two would let a client spreadsheet answer "what does the
# standard require", which is exactly the failure this platform exists to
# prevent. The model is told to keep the two apart, and the answer surfaces the
# document by name so the reader can see which claim rests on what.
_DOCUMENT_INSTRUCTIONS = (
    "=== The User's Own Uploaded Documents ===\n"
    "The excerpts below are from files the USER uploaded. They are the user's "
    "own material, not published guidance and not an authoritative source.\n"
    "  - Use them for facts about the user's own situation: their figures, "
    "their dates, their contract terms, their balances.\n"
    "  - Do NOT treat them as authority on what the law, a standard or a tax "
    "rule REQUIRES. Statements of the rules must come from your professional "
    "knowledge or from the web sources, never from the user's file.\n"
    "  - When a figure or fact comes from an uploaded document, name the "
    "document and where in it IN PROSE, as a reader would say it - for example "
    "\"your Q3 ledger, sheet 'Summary'\" or \"page 4 of your VAT return\". Do "
    "NOT write the bracketed labels used below ([DOC 1], [REF-2] and so on) "
    "anywhere in the answer; they are numbering for you, not for the reader, "
    "and the documents are listed separately underneath the answer.\n"
    "  - When the attached documents answer the question, lead with what they "
    "say. Do not open with a general explanation of how the calculation works "
    "and leave the user's own figure to the end, and do not substitute a "
    "worked example of your own for the numbers that are in front of you.\n"
    "  - If the excerpts do not contain what was asked, say so plainly and say "
    "what the document does contain. Never invent a figure that is not there, "
    "and never assume the rest of the file says what the excerpts do not.\n"
)


_DOMAIN_GATE = (
    "STEP 1 — CLASSIFY: Decide whether the user's question is about accounting, "
    "bookkeeping, taxation (income tax, corporate tax, GST/VAT/sales tax), "
    "payroll, auditing, finance, financial statements, accounting standards "
    "(IFRS/IAS/GAAP/Ind AS), tax/payroll compliance and laws, "
    "intangible assets and intellectual property — patents, trademarks, "
    "copyrights, licences, brands and goodwill, including how they are "
    "recognised, valued, amortised, impaired and taxed (a bare question "
    "such as 'what are intellectual properties' IS in scope: these are "
    "balance-sheet assets under IAS 38, so explain them from the "
    "accounting and tax perspective), accounting "
    "software, commerce, accounting education/certifications, economic and "
    "fiscal statistics (GDP, inflation/CPI, unemployment, interest rates, "
    "tax-to-GDP, public debt and similar official indicators), OR "
    "listed-company "
    "and capital-markets information — share prices and quotes, price history, "
    "company fundamentals and key figures, company profiles, statutory filings "
    "and company registers. If it is NOT "
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


def _document_block(documents: list[DocumentExcerpt]) -> str:
    """The uploaded-document evidence block, or "" when nothing is attached."""
    if not documents:
        return ""
    blocks = [
        f"[DOC {i}] {d.filename} — {d.locator}\n{d.content}"
        for i, d in enumerate(documents, start=1)
    ]
    return _DOCUMENT_INSTRUCTIONS + "\n\n".join(blocks) + "\n\n"


def build_web_grounded_prompt(
    query: str,
    sources: list[WebSource],
    documents: list[DocumentExcerpt] | None = None,
) -> str:
    """Assemble the answering prompt. When web sources were found, the model is
    told to ground its answer in them (cited separately in the UI). When none
    were found — e.g. the user gave the numbers directly and asked for a chart —
    it answers from its own knowledge, but EITHER way the table/diagram/chart
    formatting rules apply, so a requested visual is always actually drawn. An
    off-domain question is refused up front via _DOMAIN_GATE.

    `documents` are excerpts from files the user uploaded. They are added as a
    clearly separated block and are deliberately NOT merged into `sources`:
    web sources are authoritative publications the answer may state rules from,
    an uploaded file is the user's own evidence about their own situation, and
    the prompt has to keep that distinction for the answer to be safe.
    """
    documents = documents or []
    gate = _DOMAIN_GATE + (_DOCUMENT_SCOPE_NOTE if documents else "")
    docs = _document_block(documents)

    if not sources:
        # No web sources. With documents attached the answer is grounded in
        # them; with neither it falls back to the model's own knowledge.
        if documents:
            return (
                gate
                + "Answer the user's question using the excerpts from their own "
                "uploaded documents below, plus your professional knowledge for "
                "any statement of the rules. Quote the figures exactly as they "
                "appear. If the excerpts do not answer the question, say so.\n"
                + formatting_instructions(query)
                + f"\n{docs}"
                + f"=== User Question ===\n{query}"
            )
        return (
            gate
            + "Answer the user's question clearly and accurately using your own "
            "professional knowledge and any figures given in the question. Use "
            "short paragraphs or bullet points. If the user asks for a chart, "
            "table, graph or diagram, you MUST produce it in the format "
            "described below — do NOT say you cannot create visuals, and do NOT "
            "tell the user to build it in Excel/Google Sheets or with another "
            "tool; emitting the fenced code block below IS how the visual is "
            "drawn for the user.\n"
            + formatting_instructions(query)
            + f"\n=== User Question ===\n{query}"
        )
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[REF-{i}] {s.title}\nURL: {s.url}\n{s.snippet}")
    context = "\n\n".join(blocks)
    # "ONLY the web sources" is relaxed to "the web sources AND your own
    # documents" when files are attached — otherwise the instruction forbids the
    # model from using the very excerpts sitting in the same prompt.
    grounding_rule = (
        "Answer the user's question using the numbered web sources below "
        "together with the excerpts from the user's own uploaded documents. "
        "Take statements of the rules from the web sources; take the user's own "
        "figures and facts from their documents. "
        if documents else
        "Answer the user's question using ONLY the numbered web sources below. "
    )
    return (
        gate
        + grounding_rule
        + "Write a clean, natural answer. Do NOT insert citation markers such as "
        "[REF-1], [1], or source numbers anywhere in the answer text — the "
        "sources are shown to the reader separately below, so the answer must "
        "read cleanly without them. If the sources do not contain the answer, "
        "say so plainly instead of guessing. Format the answer clearly with "
        "short paragraphs or bullet points where helpful.\n"
        + formatting_instructions(query)
        + f"\n{docs}"
        + f"=== Web Sources ===\n{context}\n\n"
        + f"=== User Question ===\n{query}"
    )
