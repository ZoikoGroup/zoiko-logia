"""A requested accounting framework cannot be replaced by another one.

This final scope boundary is separate from whether a sentence is supported:
a perfectly cited IFRS rule still does not answer an exclusively US GAAP ask.
"""
from __future__ import annotations

import re

_FAMILIES = {
    "US GAAP": re.compile(r"\b(?:US\s+GAAP|U\.?S\.?\s+GAAP|ASC\s*\d+|FASB)\b", re.I),
    "IFRS": re.compile(r"\b(?:IFRS(?:\s*\d+)?|IAS\s*\d+|IASB)\b", re.I),
    "UK GAAP": re.compile(r"\b(?:UK\s+GAAP|FRS\s*\d+|FRC)\b", re.I),
    "Ind AS": re.compile(r"\bInd\s*AS(?:\s*\d+)?\b", re.I),
}


def framework_families(text: str) -> set[str]:
    return {name for name, pattern in _FAMILIES.items() if pattern.search(text or "")}


def foreign_framework_statements(question: str, answer: str, citations=()) -> list[str]:
    expected = framework_families(question)
    if len(expected) != 1:
        return []  # comparisons and unspecified frameworks retain their scope
    from app.orchestration.verification_service import _release_claim_pairs, is_evidence_gap_statement
    source_families = {
        source.ref_id: framework_families(" ".join(str(getattr(source, field, "") or "")
                                                   for field in ("title", "framework", "evidence_preview")))
        for source in citations
    }
    rejected = []
    for original, claim in _release_claim_pairs(answer):
        named = framework_families(claim)
        gap_text = original
        for pattern in _FAMILIES.values():
            gap_text = pattern.sub("the named framework", gap_text)
        cited = set().union(*(source_families.get(ref, set()) for ref in re.findall(r"\[(REF-\d+)\]", claim)))
        foreign_source_only = bool(cited - expected) and not bool(cited & expected)
        if (named - expected or foreign_source_only) and not is_evidence_gap_statement(gap_text):
            # A request to explain a difference is handled above by both
            # frameworks being named. Merely citing a foreign rule as the
            # "available evidence" cannot make it applicable.
            rejected.append(original)
    return rejected


FRAMEWORK_GAP = ("The retrieved evidence does not establish the requested accounting treatment under the named framework. "
                 "Content from another accounting framework was withheld because it cannot establish these requirements.")
