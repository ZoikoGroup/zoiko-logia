"""A requested accounting framework cannot be replaced by another one.

This final scope boundary is separate from whether a sentence is supported:
a perfectly cited IFRS rule still does not answer an exclusively US GAAP ask.
"""
from __future__ import annotations

import re

_FAMILIES = {
    # "Valuation allowance" is ASC 740's mechanism; IAS 12 does not recognise
    # the deferred tax asset instead (an IFRS deferred-tax answer used it).
    "US GAAP": re.compile(r"\b(?:US\s+GAAP|U\.?S\.?\s+GAAP|ASC\s*\d+|FASB|valuation\s+allowances?)\b", re.I),
    "IFRS": re.compile(r"\b(?:IFRS(?:\s*\d+)?|IAS\s*\d+|IASB)\b", re.I),
    "UK GAAP": re.compile(r"\b(?:UK\s+GAAP|FRS\s*\d+|FRC)\b", re.I),
    "Ind AS": re.compile(r"\bInd\s*AS(?:\s*\d+)?\b", re.I),
}
# Auditing standards are not an accounting framework. The FRC issues the UK
# auditing standards (ISA (UK)) as well as UK GAAP, so "FRC" beside an
# auditing standard is the auditing body: an IFRS company's going-concern
# answer citing "ISA (UK) 570 … FRC" was withheld whole as "another
# accounting framework" (29 Oct 2026).
_AUDITING = re.compile(r"\bISAs?\s*(?:\(UK\)\s*)?\d{3}\b|\bISA\s*\(UK\)|\bISQ[CM]\b|\bPCAOB\b|\bAS\s*\d{4}\b|\bIAASB\b"
                       r"|\bauditing\s+standards?\b", re.I)


def framework_families(text: str) -> set[str]:
    text = text or ""
    families = {name for name, pattern in _FAMILIES.items() if pattern.search(text)}
    if "UK GAAP" in families and _AUDITING.search(text) and not re.search(r"\b(?:UK\s+GAAP|FRS\s*\d+)\b", text, re.I):
        families.discard("UK GAAP")
    return families


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
# Proportionate removal (finalisation.py, P3): a statement from another
# framework is replaced by this note and the rest of the answer stays.
FRAMEWORK_REMOVED_NOTE = "Removed: a statement from another accounting framework, which cannot establish the named framework's requirements."
FRAMEWORK_PARTIAL_NOTE = ("Incomplete answer: statements from another accounting framework were removed; they cannot "
                          "establish the requirements of the framework named in the question. The rest of the answer is shown.")
