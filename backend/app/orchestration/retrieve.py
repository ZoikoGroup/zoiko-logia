"""
Massarius™ source retrieval layer — ZL-ENG-02 §7.

MVP: category-keyword source selection. Pre-RAG.
DO NOT label this as RAG in code comments, docs or external materials until §7 criteria are met:
  embeddings, chunking, semantic retrieval, ranking, re-ranking, citation binding,
  retrieval evaluation, hallucination checks and source freshness handling.

retrieval_method = "keyword_mvp" in all SourceBundle responses.

Category *routing* (infer_category) has an embedding-similarity fallback
(_infer_category_semantic) for queries the keyword list misses entirely —
this is unrelated to and does not touch the §7 "semantic retrieval"
criterion above, which is about *document* retrieval/chunking/ranking, not
category routing. retrieval_method stays "keyword_mvp" regardless.

Tenant isolation: every source_library query carries tenant_id at the data-access layer.
Application-level filtering alone is not sufficient (§7.1).
"""
from __future__ import annotations

import uuid
import os
import re
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.source_library.service import list_sources, get_source_by_id
from app.orchestration.schemas import SourceBundle, SourceSummary
from app.orchestration.routing_matrix import (
    CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT,
    CONF_CONFLICTING, CONF_STALE, CONF_RESTRICTED,
)
from app.domains.reference_data.service import (
    TREASURY_GOVERNED_SOURCE_ID, PAYROLL_TAX_GOVERNED_SOURCE_ID,
    CENSUS_GOVERNED_SOURCE_ID, BLS_CPI_GOVERNED_SOURCE_ID,
    BEA_GDP_GOVERNED_SOURCE_ID, FRED_INTEREST_RATES_GOVERNED_SOURCE_ID,
    CFR_TITLE26_GOVERNED_SOURCE_ID, FEDERAL_REGISTER_GOVERNED_SOURCE_ID,
    ECFR_TITLE26_GOVERNED_SOURCE_ID,
    CONGRESS_GOVERNED_SOURCE_ID,
    TAVILY_GOVERNED_SOURCE_ID, SERPAPI_GOVERNED_SOURCE_ID,
)
from app.domains.calculation.service import POLICYENGINE_GOVERNED_SOURCE_ID
from app.domains.reference_data.bank_reconciliation import BANK_RECONCILIATION_GOVERNED_SOURCE_ID
from app.domains.reference_data.month_end_close import MONTH_END_CLOSE_GOVERNED_SOURCE_ID
from app.domains.reference_data.accounting_fundamentals import ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID
from app.domains.reference_data.user_provided_data import USER_PROVIDED_DATA_GOVERNED_SOURCE_ID

settings = get_settings()

# Sources fetched live and deterministically per-query (Treasury, GovInfo,
# eCFR, Census, BLS, BEA, FRED, Federal Register, PolicyEngine calculation)
# rather than matched incidentally by keyword against a static document.
# len(eligible) == 1 is a legitimate "weaker evidence" signal for a keyword
# hit against one static document out of many candidates — but not for
# these: each one is *structurally* limited to exactly one eligible source
# per query (there's nothing else in that category left to corroborate
# against), so the same rule permanently capped them at CONF_LIMITED and
# routed every MEDIUM-risk query in these categories to human review
# regardless of how fresh or authoritative the fetched data actually was.
# Verified live (2026-07-21): a Treasury/FICA/FRED query with correct,
# freshly-fetched data was escalating purely on this count-based rule.
_SINGLE_SOURCE_IS_SUFFICIENT: set[str] = {
    TREASURY_GOVERNED_SOURCE_ID, PAYROLL_TAX_GOVERNED_SOURCE_ID,
    CENSUS_GOVERNED_SOURCE_ID, BLS_CPI_GOVERNED_SOURCE_ID,
    BEA_GDP_GOVERNED_SOURCE_ID, FRED_INTEREST_RATES_GOVERNED_SOURCE_ID,
    CFR_TITLE26_GOVERNED_SOURCE_ID, FEDERAL_REGISTER_GOVERNED_SOURCE_ID,
    ECFR_TITLE26_GOVERNED_SOURCE_ID, POLICYENGINE_GOVERNED_SOURCE_ID,
    CONGRESS_GOVERNED_SOURCE_ID,
    BANK_RECONCILIATION_GOVERNED_SOURCE_ID, MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
    ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
    USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
}

# A single directly-on-point primary publication can be sufficient for a
# basic scope/definition question. Counting documents is not corroboration:
# requiring two sources made "What does IRS Publication 15 cover?" escalate
# even though Publication 15 itself is the controlling primary source.
_SINGLE_AUTHORITATIVE_TITLE_MARKERS = (
    "irs publication 15",
    "irs publication 946",
    "asc 606",
    "pcaob as 2201",
    "bureau of economic analysis",
    "federal reserve economic data",
)

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "user-provided-data": ["using this data", "use this data", "based on this data", "budget versus actual"],
    "bank-reconciliation": [
        "bank reconciliation", "reconcile a bank", "reconcile the bank",
        "reconcile bank account", "cash reconciliation", "outstanding checks",
        "deposits in transit",
    ],
    "month-end-close": [
        "month-end close", "month end close", "financial closing process",
        "financial close process", "period-end close", "period end close",
        "closing checklist", "close calendar",
    ],
    "accounting-fundamentals": [
        "cash accounting", "cash-basis accounting", "cash basis accounting",
        "accrual accounting", "accrual-basis accounting", "accrual basis accounting",
        "trial balance", "unadjusted trial balance", "adjusted trial balance",
        "accounts-payable process", "accounts payable process", "order-to-cash", "order to cash",
        "audit evidence process", "audit-evidence process", "audit evidence workflow",
    ],
    # Must come before "tax" — a query mentioning both ("exchange rate for
    # tax purposes") should route here, not fall into the generic "tax"
    # keyword match first.
    "exchange-rate": ["exchange rate", "exchange rates", "currency exchange", "fx rate", "foreign exchange"],
    # Must come before "tax" for the same reason as exchange-rate above — a
    # query mentioning both ("payroll tax rates for California") should
    # route here, not fall into the generic "tax" keyword match first.
    # "payroll"/"employment" alone missed realistic phrasing like "FICA rate"
    # or "SUTA rate" that never says either word — confirmed via live testing
    # (e.g. "What is the FICA rate in Texas?" fell through to "standards"
    # with zero payroll keywords matched, so the payroll-tax live-fetch
    # injection never even ran).
    "payroll-compliance": [
        "payroll", "employment", "fica", "suta", "futa",
        "withholding tax", "unemployment insurance", "unemployment tax",
    ],
    # Compound phrases only — a bare "income" would collide with the
    # existing "tax"/PolicyEngine income-tax content this category is
    # deliberately kept separate from.
    "economic-data": [
        "median household income", "median income", "poverty rate",
        "poverty threshold", "poverty level", "census data",
        "inflation rate", "inflation", "consumer price index", "cpi",
        "cost of living", "gdp", "gross domestic product",
    ],
    # Compound phrases only — deliberately excludes a bare "interest rate",
    # which is just as likely to mean the IRS's quarterly underpayment/
    # overpayment interest rate (a tax-specific concept, already covered
    # elsewhere) as one of FRED's market rates.
    "interest-rates": [
        "federal funds rate", "fed funds rate", "prime rate",
        "treasury yield", "10-year treasury", "30-year treasury",
        "mortgage rate",
    ],
    # Must come before "tax" — a query naming a specific regulation
    # ("26 CFR 1.401(k)-1") should route here for the live section lookup,
    # not fall into the generic "tax" keyword match first.
    "tax-regulations": [
        "cfr", "code of federal regulations", "treasury regulation",
        "treas. reg", "treas reg", "26 cfr",
    ],
    "federal-register": ["federal register"],
    "us-legislation": [
        "congress.gov", "congressional bill", "house bill", "senate bill",
        "h.r.", "th congress",
    ],
    # "tax" alone missed realistic phrasing that never says the word "tax"
    # at all — confirmed via live testing (e.g. "What is the standard
    # deduction for a single filer in 2026?" fell through to the "standards"
    # default category with zero tax keywords matched), same class of gap
    # already fixed once for payroll-compliance's FICA/SUTA/FUTA terms.
    # Same gap hit again, live, for calculation.py's PolicyEngine injection:
    # "What's my EITC for $32,000 income, Head of Household, 2 kids, 2025?"
    # names no "tax"/"deduction" keyword at all, so infer_category() fell to
    # "standards", the calculation injection block never ran, and the LLM
    # fabricated its own EITC arithmetic from raw parameter markdown instead
    # — the exact failure mode the calculation engine exists to prevent.
    "tax": [
        "tax", "deduction", "eitc", "earned income credit", "earned income tax credit",
        "ctc", "child tax credit", "child and dependent care credit", "cdcc",
    ],
    "audit": ["audit", "going concern"],
    "internal-policies": ["internal policy", "firm policy"],
    "education-content": ["exam", "study", "cpd", "syllabus"],
}
_DEFAULT_CATEGORY = "standards"

# Fallback for when _CATEGORY_KEYWORDS finds nothing — natural example
# phrases per category (not keywords), matched by embedding similarity.
# Unlike _CATEGORY_KEYWORDS above, matching here is *best score across all
# categories*, not *first match in dict order* — the "must come before tax"
# ordering comments on the keyword bank don't apply to this bank at all.
# Includes both real, live-tested keyword-list misses (FICA/Texas,
# EITC/$32,000/HoH) as anchors, since those are exactly the failure mode
# this fallback exists to generalize away from needing hand-patched
# keywords for every future phrasing variant.
_CATEGORY_EXAMPLES: dict[str, list[str]] = {
    "user-provided-data": [
        "Show a table and chart using this data: Q1 revenue 100 and Q2 revenue 120.",
        "Analyze the figures I provided in this request.",
    ],
    "bank-reconciliation": [
        "Give me the steps to reconcile a bank account.",
        "How do I complete a monthly bank reconciliation?",
        "How should deposits in transit and outstanding checks be handled?",
    ],
    "month-end-close": [
        "Show the month-end financial closing process as a timeline.",
        "What is the month-end close checklist?",
        "Explain the period-end financial close process.",
    ],
    "accounting-fundamentals": [
        "Compare cash accounting and accrual accounting.",
        "Explain how accrual accounting works in practice.",
        "Show the audit evidence process as a flow chart.",
    ],
    "exchange-rate": [
        "What's the exchange rate between USD and EUR today?",
        "How many Japanese yen equal one US dollar right now?",
        "I need the current dollar-to-peso conversion rate.",
        "What's the FX rate for the Canadian dollar this quarter?",
    ],
    "payroll-compliance": [
        "What is the FICA rate in Texas?",
        "How much SUTA do I owe for a new hire in Ohio?",
        "What's the current federal unemployment insurance rate?",
        "What are the payroll withholding requirements for a household employer in California?",
    ],
    "economic-data": [
        "What's the median household income in Texas right now?",
        "How has the poverty rate changed since the last census?",
        "What was last month's inflation number?",
        "How big is the US economy in GDP terms this year?",
    ],
    "interest-rates": [
        "What's the current federal funds rate?",
        "Where is the 10-year treasury yield trading today?",
        "What's the average 30-year mortgage rate right now?",
        "What's the prime rate banks are charging their best customers?",
    ],
    "tax-regulations": [
        "What does 26 CFR 1.401(k)-1 say about elective deferrals?",
        "Can you pull up the treasury regulation on like-kind exchanges?",
        # Not "...for depreciation schedules" (the original wording here) —
        # confirmed live (2026-07-21): a general question about how
        # depreciation affects the three financial statements scored as
        # semantically similar to this example on the shared word
        # "depreciation" alone, misrouting it to a CFR-section lookup
        # category (and reporting spurious "eligible" sources for a
        # question those sources don't actually address) instead of being
        # recognized as the general accounting-concept question it is.
        # Required minimum distributions carries the same "specific CFR
        # lookup" intent without a topic word this likely to collide with
        # ordinary accounting-education phrasing.
        "What's in the code of federal regulations for required minimum distribution rules?",
    ],
    "federal-register": [
        "Was there a recent Federal Register notice on this rule?",
        "Has the IRS published a new proposed rule in the Federal Register?",
        "When was this regulation's final rule published?",
    ],
    "us-legislation": [
        "What is the status of H.R. 1 in the 119th Congress?",
        "Summarize S. 5 from the 119th Congress.",
        "What was the latest action on this congressional bill?",
    ],
    "tax": [
        "What's my EITC for $32,000 income, Head of Household, 2 kids, 2025?",
        "How much is the Child Tax Credit worth this year?",
        "What's the standard deduction for a single filer in 2026?",
        "What tax bracket am I in if I make $85,000?",
    ],
    "audit": [
        "Is there a going concern issue with this client's financials?",
        "What does the audit opinion need to say for a qualified opinion?",
        "What audit procedures should I run for accounts receivable?",
    ],
    "internal-policies": [
        "What's our firm's policy on accepting client gifts?",
        "Does our internal policy allow remote client meetings?",
        "What's the firm's engagement letter policy?",
    ],
    "education-content": [
        "What topics are on the REG section of the CPA exam?",
        "How many CPD hours do I need this year?",
        "Is there a study guide for the FAR exam syllabus?",
    ],
}

_category_example_embeddings: dict[str, list] | None = None


def _get_category_example_embeddings() -> dict[str, list]:
    global _category_example_embeddings
    if _category_example_embeddings is None:
        from app.domains.rag.embeddings import get_embed_model

        model = get_embed_model()
        _category_example_embeddings = {
            category: model.get_text_embedding_batch(examples)
            for category, examples in _CATEGORY_EXAMPLES.items()
        }
    return _category_example_embeddings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _infer_category_semantic(query: str) -> str | None:
    """Embedding-similarity fallback for infer_category() — reuses the
    shared rag/embeddings.py::get_embed_model() singleton already loaded
    whenever ENABLE_RAG_EMBEDDINGS is on, no second model load. Returns
    None (never raises) if that flag is off, the embedding call fails for
    any reason, or nothing clears settings.CATEGORY_SEMANTIC_THRESHOLD —
    callers must fall back to _DEFAULT_CATEGORY on None, today's exact
    existing behavior when the keyword scan also finds nothing."""
    if os.getenv("ENABLE_RAG_EMBEDDINGS", "").lower() not in {"1", "true", "yes"}:
        return None
    try:
        from app.domains.rag.embeddings import get_embed_model

        model = get_embed_model()
        query_embedding = model.get_text_embedding(query)
        best_category, best_score = None, -1.0
        for category, embeddings in _get_category_example_embeddings().items():
            score = max(_cosine_similarity(query_embedding, e) for e in embeddings)
            if score > best_score:
                best_category, best_score = category, score
        return best_category if best_score >= settings.CATEGORY_SEMANTIC_THRESHOLD else None
    except Exception:
        return None

# Sources with these statuses are eligible for retrieval
_ELIGIBLE_STATUSES = {"ACTIVE", "APPROVED"}

# Sources with these statuses are excluded as restricted
_RESTRICTED_STATUSES = {"DRAFT", "DEPRECATED", "BLOCKED", "RESTRICTED"}


@lru_cache(maxsize=256)
def infer_category(query: str) -> str:
    """Keyword match always wins when it hits (unchanged, zero behavior
    change for every query already routed correctly today) — semantic
    classification only runs as a fallback for the silent-default-to-
    "standards" case, the exact failure mode that's already bitten this
    codebase twice live (FICA/Texas phrasing, then EITC/HoH phrasing).
    Cached: this function is called ~10 times per single ask_kriton()
    request with the identical query string (once per live-data category
    gate in orchestration/service.py) — without caching, a query that falls
    through to the semantic path would pay the embedding-inference cost up
    to 10x per request for identical input, the same redundant-recompute
    anti-pattern already eliminated once in this codebase for
    retrieve_documents() (see build_source_bundle's raw_chunks docstring)."""
    lowered = query.lower()
    if (
        re.search(r"\b(chart|graph|plot|visuali[sz]e|compare|table)\b", lowered)
        and len(re.findall(r"[$£€]\s*[\d,]+(?:\.\d+)?", query)) >= 2
    ):
        return "user-provided-data"
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(_keyword_matches(lowered, keyword) for keyword in keywords):
            return category
    semantic_category = _infer_category_semantic(query)
    return semantic_category if semantic_category is not None else _DEFAULT_CATEGORY


def _keyword_matches(lowered_query: str, keyword: str) -> bool:
    """Match keywords without allowing embedded-token collisions.

    The previous substring check classified ``ICFR`` as tax regulations
    because it contains ``cfr``. Alphanumeric-ended keywords use explicit
    word boundaries; punctuation identifiers such as ``h.r.`` retain literal
    substring matching.
    """
    if keyword and keyword[0].isalnum() and keyword[-1].isalnum():
        return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", lowered_query) is not None
    return keyword in lowered_query


async def build_source_bundle(
    db: AsyncSession,
    *,
    query: str,
    jurisdiction: str,
    tenant_id: str,
    raw_chunks: list | None = None,
) -> SourceBundle:
    """
    Build a SourceBundle via keyword-based category retrieval, merged with
    governance-verified vector search hits.
    tenant_id is enforced at the data-access layer via list_sources /
    get_source_by_id.
    Returns confidence_state per §7.2 six-state vocabulary.

    raw_chunks: pass already-fetched vector search results (e.g. the same
    chunks orchestration/service.py separately fetches at a larger top_k for
    the LLM's grounded context) to skip this function's own retrieve_documents()
    call entirely. retrieve_documents() embeds the query text and does a real
    Postgres vector search — profiling showed it costs ~20s per call on this
    setup, and it was previously being called twice per request (once here at
    top_k=5, once in service.py at top_k=30) for the exact same query, which
    is pure waste. Pass None (the old behavior) to have this function fetch
    its own chunks, e.g. for standalone/test use.
    """
    category = infer_category(query)

    eligible = []
    excluded = []
    exclusion_reasons = []
    has_restricted = False
    has_conflict = False

    # Always resolve the governed keyword_mvp candidates first — vector hits
    # below are additive evidence, never a replacement for this. Previously,
    # any non-empty vector result short-circuited this list entirely (an
    # `if vector_sources: ... else: ...` branch), so a single unrelated
    # vector match — or a chunk embedded outside the governance workflow —
    # could make a properly registered, ACTIVE source disappear from the
    # bundle with no error at all.
    candidates = await list_sources(db, category, tenant_id=tenant_id)
    seen_ids = set()
    # Sources fetched live per-query (Treasury, GovInfo, eCFR, Census, BLS,
    # BEA, FRED, Federal Register, PayrollTax, PolicyEngine calculation —
    # the same set as _SINGLE_SOURCE_IS_SUFFICIENT above) only ever produce
    # real content when the query's required identifier (a CFR section, a
    # currency name, a US state, ...) is extractable — a category match
    # alone just means "this source is registered and allowed," not "we
    # retrieved anything for this query." For a static ingested document
    # that distinction never mattered (a category match meant real embedded
    # content existed by construction), but confirmed live (2026-07-21):
    # "What does 26 CFR say about like-kind exchanges?" named no section
    # number, so the live fetch correctly never ran (extract_cfr_section's
    # own contract: None means don't call the API) — yet GovInfo/eCFR still
    # reported "2 eligible, sufficient confidence," composition then had
    # nothing real to answer from, and produced an empty response despite
    # the reported confidence. Cross-checking against raw_chunks closes that
    # gap without changing anything for static ingested sources (raw_chunks
    # is only None for standalone/test callers per this function's own
    # docstring, so has_real_content defaults to True there — unchanged
    # behavior for those callers).
    chunk_source_ids = (
        {c.get("metadata", {}).get("source_id") for c in raw_chunks}
        if raw_chunks is not None else None
    )
    for c in candidates:
        version_status = c["latest_version"].status
        jur_ok = (not jurisdiction) or c["jurisdiction_scope"] in ("Global", jurisdiction)
        is_live_fetch_only = c["id"] in _SINGLE_SOURCE_IS_SUFFICIENT
        has_real_content = chunk_source_ids is None or c["id"] in chunk_source_ids

        if version_status in _RESTRICTED_STATUSES:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' has restricted status: {version_status}")
            has_restricted = True
        elif version_status not in _ELIGIBLE_STATUSES:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' has ineligible status: {version_status}")
        elif not jur_ok:
            excluded.append(c)
            exclusion_reasons.append(f"Source '{c['title']}' outside jurisdiction scope")
        elif is_live_fetch_only and not has_real_content:
            excluded.append(c)
            exclusion_reasons.append(
                f"Source '{c['title']}' is category-eligible but no live data was retrieved for this specific query"
            )
        else:
            eligible.append(c)
        seen_ids.add(c["id"])

    if os.getenv("ENABLE_RAG_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        # ── Vector Search ──
        # Chunk metadata is untrusted as far as governance goes — it's
        # whatever was present at embed time, which can go stale (a source
        # later deprecated) or never have existed as a real governed record
        # at all (chunks embedded outside create_source/approve_source_version,
        # e.g. via the upload path). Every hit is re-checked against the real
        # sources/source_versions record by source_id, through the same
        # status/jurisdiction rules as the keyword path above — never taken
        # at face value as "ACTIVE".
        try:
            if raw_chunks is None:
                from app.domains.rag.retrieval import retrieve_documents

                raw_chunks = await retrieve_documents(
                    query=query,
                    tenant_id=tenant_id,
                    jurisdiction=jurisdiction or None,
                    top_k=5
                )
            checked_source_ids = set()
            for chunk in raw_chunks:
                meta = chunk.get("metadata", {})
                source_id = meta.get("source_id")
                title = meta.get("title", "unknown")
                if not source_id:
                    exclusion_reasons.append(
                        f"Vector chunk '{title}' has no linked source_id — not embedded via the governed source workflow, excluded"
                    )
                    continue
                if source_id in seen_ids or source_id in checked_source_ids:
                    continue
                checked_source_ids.add(source_id)

                governed = await get_source_by_id(db, source_id, tenant_id=tenant_id)
                if governed is None:
                    exclusion_reasons.append(f"{source_id}: source_record_not_found")
                    continue

                version_status = governed["latest_version"].status if governed["latest_version"] else None
                jur_ok = (not jurisdiction) or governed["jurisdiction_scope"] in ("Global", jurisdiction)

                if version_status in _RESTRICTED_STATUSES:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' has restricted status: {version_status}")
                    has_restricted = True
                elif version_status not in _ELIGIBLE_STATUSES:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' has ineligible status: {version_status}")
                elif not jur_ok:
                    excluded.append(governed)
                    exclusion_reasons.append(f"Source '{governed['title']}' outside jurisdiction scope")
                else:
                    eligible.append(governed)
                    seen_ids.add(source_id)
        except Exception as e:
            exclusion_reasons.append(f"Vector store search failed: {str(e)}")

    # Determine confidence_state per §7.2
    if has_restricted and len(eligible) == 0:
        confidence_state = CONF_RESTRICTED
    elif len(eligible) == 0:
        confidence_state = CONF_INSUFFICIENT
    elif (
        len(eligible) == 1
        and eligible[0]["id"] not in _SINGLE_SOURCE_IS_SUFFICIENT
        and not any(
            marker in eligible[0]["title"].lower()
            for marker in _SINGLE_AUTHORITATIVE_TITLE_MARKERS
        )
    ):
        confidence_state = CONF_LIMITED
    elif has_conflict:
        confidence_state = CONF_CONFLICTING
    else:
        confidence_state = CONF_SUFFICIENT

    # Determine authority_level from category
    authority_level = "primary" if category in ("audit", "tax", "exchange-rate") else "secondary"

    explicit_scopes = {
        c["jurisdiction_scope"] for c in eligible
        if c["jurisdiction_scope"] and c["jurisdiction_scope"] != "Global"
    }
    us_authority_present = any(
        marker in c["title"].lower()
        for c in eligible
        for marker in ("irs ", "pcaob", "congress.gov", "sec ", "u.s. code")
    )
    national_us_data = category in {"economic-data", "interest-rate", "exchange-rate"}
    resolved_jurisdiction = (
        "US" if us_authority_present or national_us_data
        else jurisdiction
    ) or (
        next(iter(explicit_scopes)) if len(explicit_scopes) == 1
        else ""
    )

    return SourceBundle(
        source_bundle_id=f"sb-{uuid.uuid4().hex[:12]}",
        retrieval_method="keyword_mvp",  # §7: do not label as RAG
        eligible_source_count=len(eligible),
        excluded_source_count=len(excluded),
        sources=[
            SourceSummary(
                id=c["id"],
                title=c["title"],
                category=c["category"],
                jurisdiction_scope=c["jurisdiction_scope"],
                version_label=c["latest_version"].version_label,
                status=c["latest_version"].status,
            )
            for c in eligible
        ],
        exclusion_reasons=exclusion_reasons,
        jurisdiction=resolved_jurisdiction,
        authority_level=authority_level,
        freshness_state="unknown",   # TODO: implement freshness check in full RAG phase
        licence_state="permitted",   # MVP assumption; enforce per-source in production
        confidence_state=confidence_state,
    )
