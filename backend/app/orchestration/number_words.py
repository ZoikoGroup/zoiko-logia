"""
Spelled-out small numbers ("ten", "twenty-five") for the query-side regexes
that parse a time span ("the last N years"). Several of those regexes only
ever matched a digit span (\\d+) — "the last ten years" silently failed to
match while "the last 10 years" worked. Found via this session's semantic-
classifier evaluation (a permanent regression case there), reproduced live
in the app, and fixed here once so every call site (intent_classifier.py's
_TREND_HINTS, market_data/registry.py's _SPAN and INTENT_HISTORY pattern)
shares the same word list instead of three independently-drifting copies.

Deliberately scoped to 1-99 plus "hundred" — real questions in this domain
say "the last thirty years", never "the last three hundred and forty-two
days"; full general English number parsing is a bigger task this specific,
narrow gap doesn't call for.
"""
from __future__ import annotations

import re

_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORDS = {**_ONES, **_TEENS, **_TENS, "hundred": 100}

# A single spelled number ("ten") or a tens+ones compound ("twenty five" /
# "twenty-five"), for embedding inside a larger pattern alongside \d+.
# Longest-first so "seventeen" doesn't get cut short by a shorter prefix.
_SORTED_WORDS = sorted(_WORDS, key=len, reverse=True)
SPELLED_NUMBER_PATTERN = (
    r"(?:" + "|".join(_TENS) + r")[\s-](?:" + "|".join(_ONES) + r")"
    r"|(?:" + "|".join(_SORTED_WORDS) + r")"
)

_SPELLED_NUMBER_RE = re.compile(SPELLED_NUMBER_PATTERN, re.I)
_COMPOUND_RE = re.compile(
    r"^(?P<tens>" + "|".join(_TENS) + r")[\s-](?P<ones>" + "|".join(_ONES) + r")$", re.I,
)


def spelled_number_to_int(text: str) -> int | None:
    """Parse a spelled-out number this module recognizes ("ten", "twenty
    five", "twenty-five") back to an int, or None if it isn't one."""
    normalized = text.strip().lower()
    compound = _COMPOUND_RE.match(normalized)
    if compound:
        return _TENS[compound.group("tens")] + _ONES[compound.group("ones")]
    return _WORDS.get(normalized)


def find_first_spelled_number(text: str) -> int | None:
    """First spelled-out number found anywhere in `text`, or None."""
    match = _SPELLED_NUMBER_RE.search(text or "")
    if not match:
        return None
    return spelled_number_to_int(match.group(0))
