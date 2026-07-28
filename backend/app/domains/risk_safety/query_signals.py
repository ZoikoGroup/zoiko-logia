"""Deterministic, explainable signals used by the risk-classification policy.

These signals are deliberately multi-label: a query can be about tax, request
an interpretation, name a real client, and omit a jurisdiction at the same
time.  They do not decide the final route; ``risk_classifier`` remains the
single policy authority.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_TOPICS: dict[str, re.Pattern[str]] = {
    "tax": re.compile(r"\b(tax(?:es)?|irs|return|deduction|withholding|payroll)\b", re.I),
    "audit": re.compile(r"\b(audit(?:or|ing)?|assurance|evidence|pcaob|confirmation)\b", re.I),
    "accounting": re.compile(
        r"\b(account(?:ing)?|journal|ledger|debit|credit|revenue|expense|asset|liabilit(?:y|ies)|lease|depreciation)\b",
        re.I,
    ),
    "reporting": re.compile(r"\b(report(?:ed|ing)?|financial statements?|asc|ifrs|ias|gaap)\b", re.I),
    "legal_compliance": re.compile(r"\b(legal|law|regulat(?:or|ion|ory)|compliance|fraud)\b", re.I),
    "finance": re.compile(r"\b(finance|gdp|inflation|interest|exchange rate|treasury|yield)\b", re.I),
}

_PERSONAL_ENTITIES = re.compile(
    r"\b(my|our)\s+(company|client|firm|business|tax(?:es)?|return|audit|filing|situation|case)\b",
    re.I,
)
_RECOMMENDATION = re.compile(r"\b(advise|recommend|what should|should)\b", re.I)
_PERSONAL_RECOMMENDATION = re.compile(
    r"\b(should\s+(?:i|we|my|our)|what\s+(?:should|do)\s+(?:i|we)|advise\s+(?:me|us|my|our))\b",
    re.I,
)
_CALCULATION = re.compile(r"^\s*(calculate|compute)\b|\bwhat\s+is\s+the\s+(?:net|total|amount|percentage)\b", re.I)
_INTERPRETATION = re.compile(r"\b(assess|evaluate|interpret|treatment|recognize|classif(?:y|ication))\b", re.I)
_NAVIGATION = re.compile(r"\b(find|open|access|dashboard|saved answers|what can kriton)\b", re.I)
_JURISDICTION_TERMS = re.compile(
    r"\b(USA|United States|UK|United Kingdom|EU|European Union|Australia|Canada|India)\b",
    re.I,
)
_US_CODE = re.compile(r"\bUS\b")  # case-sensitive: do not treat pronoun "us" as a jurisdiction


@dataclass(frozen=True)
class QuerySignals:
    topics: tuple[str, ...]
    intents: tuple[str, ...]
    personalized_advice: bool
    jurisdiction_supplied: bool
    jurisdiction_mentions: tuple[str, ...]
    missing_context: tuple[str, ...]

    def to_dict(self) -> dict:
        result = asdict(self)
        # JSON-facing metadata uses arrays, not dataclass tuples.
        for field in ("topics", "intents", "jurisdiction_mentions", "missing_context"):
            result[field] = list(result[field])
        return result


def analyze(query: str, *, jurisdiction: str = "", ambiguous: bool = False) -> QuerySignals:
    """Extract stable policy signals without sending query text to a model."""
    topics = tuple(name for name, pattern in _TOPICS.items() if pattern.search(query))
    personalized = bool(_PERSONAL_ENTITIES.search(query) or _PERSONAL_RECOMMENDATION.search(query))

    intents: list[str] = []
    if _RECOMMENDATION.search(query):
        intents.append("recommendation")
    if _INTERPRETATION.search(query):
        intents.append("interpretation")
    if _CALCULATION.search(query):
        intents.append("calculation")
    if _NAVIGATION.search(query):
        intents.append("navigation")
    if not intents:
        intents.append("information")

    mentions = tuple(dict.fromkeys(
        [match.group(0) for match in _JURISDICTION_TERMS.finditer(query)]
        + [match.group(0) for match in _US_CODE.finditer(query)]
    ))
    jurisdiction_supplied = bool(jurisdiction.strip() or mentions)
    missing: list[str] = []
    if personalized and any(topic in {"tax", "legal_compliance"} for topic in topics) and not jurisdiction_supplied:
        missing.append("jurisdiction")
    if ambiguous:
        missing.extend(("subject", "reporting_context"))

    return QuerySignals(
        topics=topics or ("general",),
        intents=tuple(intents),
        personalized_advice=personalized,
        jurisdiction_supplied=jurisdiction_supplied,
        jurisdiction_mentions=mentions,
        missing_context=tuple(dict.fromkeys(missing)),
    )
