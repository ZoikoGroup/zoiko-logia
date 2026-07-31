"""Latency-bounded, policy-subordinate query understanding for Ask Kriton."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass, replace
from functools import lru_cache

from app.domains.risk_safety import llm_classifier
from app.domains.risk_safety.query_signals import analyze as analyze_query_signals


QUERY_UNDERSTANDING_VERSION = "query-understanding-v1"

_CURRENT = re.compile(
    r"\b(current|currently|today|latest|recent|now|rate|effective date|this year|202[4-9])\b",
    re.I,
)
_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("flowchart", re.compile(r"\b(flow[ -]?chart|decision\s+tree)\b", re.I)),
    ("table", re.compile(r"\b(table|tabular)\b", re.I)),
    ("chart", re.compile(r"\b(chart|graph|plot|visuali[sz]e)\b(?!\s+of\s+accounts)", re.I)),
    ("comparison", re.compile(r"\b(compare|comparison|versus|vs\.?|difference between)\b", re.I)),
    ("step_by_step", re.compile(r"\b(step[- ]by[- ]step|steps?|checklist|process|procedure|how do)\b", re.I)),
    ("calculation", re.compile(r"\b(calculate|compute|work out|how much|formula)\b", re.I)),
    ("summary", re.compile(r"\b(summar(?:y|ise|ize)|key points?|tl;?dr)\b", re.I)),
    ("plain_language", re.compile(r"\b(simple|simply|plain language|easy to understand|layman)\b", re.I)),
    ("detailed", re.compile(r"\b(detailed|in depth|comprehensive|thorough)\b", re.I)),
)
_INTENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("compare", re.compile(r"\b(compare|comparison|versus|vs\.?|difference between)\b", re.I)),
    ("calculate", re.compile(r"\b(calculate|compute|work out|how much|formula)\b", re.I)),
    ("summarize", re.compile(r"\b(summar(?:y|ise|ize)|key points?|tl;?dr)\b", re.I)),
    ("draft", re.compile(r"\b(draft|write|prepare|compose)\b", re.I)),
    ("recommend", re.compile(r"\b(advise|recommend|what should|should (?:i|we|our|my))\b", re.I)),
    ("interpret", re.compile(r"\b(assess|evaluate|interpret|treatment|recognition|classify)\b", re.I)),
    ("find_document", re.compile(r"\b(find|locate|pull up|show me)\b.*\b(document|filing|regulation|standard|policy|source)\b", re.I)),
    ("find_current_value", re.compile(r"\b(current|today|latest|recent)\b.*\b(rate|value|figure|data|filing|bill)\b", re.I)),
    ("explain", re.compile(r"\b(explain|define|what (?:is|are|does)|how does|help me understand)\b", re.I)),
    ("steps", re.compile(r"\b(steps?|checklist|process|procedure|how do)\b", re.I)),
)
_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tax", re.compile(r"\b(tax|irs|deduction|credit|payroll|withholding|cfr)\b", re.I)),
    ("audit", re.compile(r"\b(audit|assurance|going concern|pcaob|evidence)\b", re.I)),
    ("accounting", re.compile(
        r"\b(accounting|ifrs|ias(?:\s*\d+)?|gaap|asc(?:\s*\d+)?|journal|ledger|"
        r"revenue|expense|lease|depreciation|impairment|bank[ -]reconciliation|"
        r"month[ -]end(?:\s+financial)?\s+close|recognition)\b",
        re.I,
    )),
    ("finance", re.compile(r"\b(exchange rate|interest rate|gdp|inflation|treasury|finance)\b", re.I)),
    ("compliance", re.compile(r"\b(compliance|regulation|legal|filing|reporting requirement)\b", re.I)),
)
_POLITE_PREFIX = re.compile(
    r"^\s*(?:(?:hi|hello|hey)[,!]?\s+)?(?:(?:please|kindly)\s+)?"
    r"(?:(?:can|could|would)\s+you\s+)?",
    re.I,
)
_STYLE_NOISE = re.compile(
    r"\b(?:in simple terms|in plain language|simply|briefly|in detail|for a beginner)\b",
    re.I,
)


@dataclass(frozen=True)
class QueryUnderstanding:
    primary_intent: str
    domain: str
    retrieval_query: str
    response_format: str
    requested_depth: str
    requires_current_sources: bool
    personalized: bool
    missing_context: tuple[str, ...]
    risk_signals: tuple[str, ...]
    confidence: float
    source: str
    latency_ms: float
    version: str = QUERY_UNDERSTANDING_VERSION

    def audit_payload(self) -> dict:
        payload = asdict(self)
        payload.pop("retrieval_query", None)
        payload["missing_context"] = list(self.missing_context)
        payload["risk_signals"] = list(self.risk_signals)
        return payload


def _response_format(query: str) -> str:
    for name, pattern in _FORMATS:
        if pattern.search(query):
            return name
    return "adaptive"


def _intent(query: str) -> tuple[str, float]:
    for name, pattern in _INTENTS:
        if pattern.search(query):
            return name, 0.94
    if len(query.split()) >= 4:
        return "information", 0.55
    return "unknown", 0.45


def _domain(query: str) -> str:
    for name, pattern in _DOMAIN_PATTERNS:
        if pattern.search(query):
            return name
    return "general"


def _safe_retrieval_query(query: str, jurisdiction: str) -> str:
    normalized = re.sub(r"\s+", " ", query).strip()
    candidate = _POLITE_PREFIX.sub("", normalized)
    candidate = _STYLE_NOISE.sub("", candidate)
    candidate = re.sub(r"\s+([?.!,])", r"\1", candidate)
    candidate = re.sub(r"\s{2,}", " ", candidate).strip(" ,")
    if len(candidate) < 8:
        candidate = normalized
    if jurisdiction and jurisdiction.lower() not in candidate.lower():
        candidate = f"{candidate} Jurisdiction: {jurisdiction}"
    return candidate[:2000]


@lru_cache(maxsize=2048)
def understand_fast(query: str, jurisdiction: str = "") -> QueryUnderstanding:
    """Sub-millisecond deterministic understanding used on every request."""
    start = time.perf_counter()
    intent, confidence = _intent(query)
    response_format = _response_format(query)
    signals = analyze_query_signals(query, jurisdiction=jurisdiction)
    domain = _domain(query)
    if intent == "information" and domain != "general":
        confidence = 0.78
    risk_signals: list[str] = []
    if signals.personalized_advice:
        risk_signals.append("personalized_advice")
    if "recommendation" in signals.intents:
        risk_signals.append("recommendation")
    requires_current = bool(_CURRENT.search(query) or intent == "find_current_value")
    requested_depth = (
        "brief" if response_format in {"concise", "summary"}
        else "detailed" if response_format == "detailed"
        else "standard"
    )
    return QueryUnderstanding(
        primary_intent=intent,
        domain=domain,
        retrieval_query=_safe_retrieval_query(query, jurisdiction),
        response_format=response_format,
        requested_depth=requested_depth,
        requires_current_sources=requires_current,
        personalized=signals.personalized_advice,
        missing_context=signals.missing_context,
        risk_signals=tuple(risk_signals),
        confidence=confidence,
        source="deterministic",
        latency_ms=(time.perf_counter() - start) * 1000,
    )


def _safe_remote_retrieval_query(original: str, proposed: str, jurisdiction: str) -> str:
    proposed = re.sub(r"\s+", " ", proposed).strip()
    if len(proposed) < 8:
        return _safe_retrieval_query(original, jurisdiction)
    # A rewrite may simplify phrasing, but it may not drop named numbers,
    # years, rates, sections, or other numeric constraints.
    original_numbers = set(re.findall(r"\b\d[\d,./%-]*\b", original))
    proposed_numbers = set(re.findall(r"\b\d[\d,./%-]*\b", proposed))
    if not original_numbers.issubset(proposed_numbers):
        return _safe_retrieval_query(original, jurisdiction)
    if jurisdiction and jurisdiction.lower() not in proposed.lower():
        proposed = f"{proposed} Jurisdiction: {jurisdiction}"
    return proposed[:2000]


async def understand(
    query: str,
    *,
    jurisdiction: str = "",
    mode: str = "Workflow",
    privacy_class: str = "NONE",
) -> QueryUnderstanding:
    """Return fast understanding, using one bounded remote fallback only for uncertainty."""
    fast = understand_fast(query, jurisdiction)
    if (
        fast.confidence >= 0.65
        or llm_classifier.configured_mode() != "fallback"
        or privacy_class != "NONE"
    ):
        return fast

    started = time.perf_counter()
    try:
        timeout = max(0.1, float(__import__("os").getenv(
            "QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "1.25",
        )))
        remote = await asyncio.wait_for(
            asyncio.to_thread(
                llm_classifier.classify,
                query,
                jurisdiction=jurisdiction,
                mode=mode,
            ),
            timeout=timeout,
        )
    except (TimeoutError, ValueError):
        return replace(fast, latency_ms=(time.perf_counter() - started) * 1000)
    if remote is None:
        return replace(fast, latency_ms=(time.perf_counter() - started) * 1000)

    return QueryUnderstanding(
        primary_intent=remote.intent or fast.primary_intent,
        domain=remote.domain or fast.domain,
        retrieval_query=_safe_remote_retrieval_query(
            query, remote.retrieval_query, jurisdiction,
        ),
        response_format=remote.response_format,
        requested_depth=remote.requested_depth,
        requires_current_sources=remote.requires_current_sources or fast.requires_current_sources,
        personalized=remote.advice_signal or fast.personalized,
        missing_context=tuple(dict.fromkeys((*fast.missing_context, *remote.missing_context))),
        risk_signals=tuple(dict.fromkeys((*fast.risk_signals, *remote.reason_codes))),
        confidence=remote.confidence,
        source="semantic_fallback",
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def build_response_instruction(result: QueryUnderstanding) -> str:
    """Deterministic composition directive; it never supplies factual content."""
    formats = {
        "plain_language": "Use plain language, short sentences, and define necessary technical terms.",
        "step_by_step": "Present the supported procedure as a numbered step-by-step sequence.",
        "comparison": "Organize supported differences consistently, using a comparison table when useful.",
        "table": "Use a compact Markdown table when the retrieved evidence supports the requested columns.",
        "chart": "Return validated numeric data in the chart format requested, with a textual table as the source of truth.",
        "flowchart": "Present the supported decision or process as a concise flowchart without inventing thresholds or branches.",
        "calculation": "Show the governed formula, substituted values, result, and methodology source.",
        "summary": "Return only the key supported points and material exceptions.",
        "detailed": "Give a structured, detailed explanation while avoiding unsupported background.",
        "concise": "Answer concisely and directly; retain material qualifications and exceptions.",
        "adaptive": "Match the amount of structure and detail to the user's task and the available evidence.",
    }
    return (
        "Response requirement: "
        + formats.get(result.response_format, formats["adaptive"])
        + " Simplification must not remove dates, thresholds, jurisdiction, exceptions, or citations."
    )
