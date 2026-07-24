"""
Elliptical follow-up detection — ZL-T0-04 context-awareness gap identified
in the intelligent-classifier design work: a query like "what about for
£20,000 instead" is unclassifiable in isolation (no tax type, no country,
no operation named) and Tier 1's exemplar-similarity classifier has no
memory of prior turns to resolve it against. Rather than trying to make an
embedding comparison understand conversation state, a cheap heuristic
decides when a query needs its predecessor's text at all — the actual
resolution then happens by the composing LLM once that context is present
in its prompt, not by this function.

Deliberately conservative: false negatives here just mean a follow-up gets
treated as a standalone query (today's existing behavior, no regression);
false positives just mean an unrelated query gets a little extra,
harmless context prepended to the grounded prompt. Neither failure mode
is unsafe, so a simple heuristic is an appropriate tool here — this is a
UX continuity aid, not a safety decision.
"""
from __future__ import annotations

import re

_CONTINUATION_STARTERS = re.compile(
    r"^\s*(and|also|what about|how about|and what about|what if instead)\b",
    re.IGNORECASE,
)
_REFERENCE_WORDS = re.compile(
    r"\b(it|that|this|those|these|instead|same|again)\b", re.IGNORECASE
)
_MAX_WORDS_FOR_SHORT_QUERY = 8


def is_elliptical_followup(query: str) -> bool:
    """True when `query` looks like it depends on a prior turn to resolve —
    starts with an explicit continuation phrase, or is short and reference-
    heavy with no clear standalone subject of its own."""
    stripped = query.strip()
    if not stripped:
        return False
    if _CONTINUATION_STARTERS.search(stripped):
        return True
    word_count = len(stripped.split())
    if word_count <= _MAX_WORDS_FOR_SHORT_QUERY and _REFERENCE_WORDS.search(stripped):
        return True
    return False
