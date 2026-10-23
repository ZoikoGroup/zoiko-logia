"""Fill an answer's explanation gaps with general accounting knowledge.

An answer marks each part its sources do not cover with "The sources provided
do not state …", and one such line made the whole answer "Partially
answered" — for gaps like "the factors that determine depreciation" that any
accountant can explain without a source. Each such explanation gap is
replaced with a short general explanation (one model call for all of them),
labelled "General explanation:". A gap about a figure, rate, threshold,
amount, date, deadline or law section is left as it is: those are never
answered without a source, and the answer stays "Partially answered" for them.
Any explanation that states a figure or a citation is discarded.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

_GAP = re.compile(
    r"\b(?:the\s+)?(?:(?:provided|retrieved|available|cited)\s+)?(?:sources?|evidence)"
    r"(?:\s+(?:provided|retrieved|available))?\s+(?:do|does|did)\s+not\s+"
    # To the full stop that ends the line, so "e.g., IAS 16" or "etc." inside
    # the sentence is not taken for its end.
    r"(?:state|confirm|establish|cover|provide|specify|mention)(?:[^\n]*?\.(?=[ \t]*(?:\n|$))|[^\n]*)",
    re.IGNORECASE,
)
# Gaps that need a source: a figure, rate, threshold, amount, date or rule reference.
_NEEDS_SOURCE = re.compile(
    r"\b(?:rate|rates|threshold|limit|amount|figure|figures|total|totals|percentage|%|deadline|due\s+date|date|"
    r"dates|penalt(?:y|ies)|section|sections|clause|notification|circular|fee|fees|price|"
    r"salary|tax\s+due|liability\s+amount)\b|\d",
    re.IGNORECASE,
)
_FIGURE = re.compile(r"%|[£$€₹¥]|\b\d{3,}\b|\[REF-", re.IGNORECASE)
_STANDARD_NAME = re.compile(r"\b(?:IFRS|IAS|IFRIC|SIC|Ind\s?AS|ISA|ASC|FRS)\s?\d{1,4}\b", re.IGNORECASE)
MAX_GAPS = 6
LABEL = "General explanation:"
NOTE = ("Parts marked “General explanation” come from established accounting knowledge, not from a cited "
        "source. Check an official source before relying on them.")
_PROMPT = (
    "You are Kriton, an assistant for accounting, tax, audit, payroll and finance. The question below was "
    "answered, but these points were not covered by the sources:\n{gaps}\n\nFor each numbered point, write "
    "one to three sentences of correct, general explanation from established accounting knowledge. Do not "
    "state any figure, percentage, rate, threshold, amount, date or section of a law, and do not cite sources. "
    "Reply with exactly one line per point, starting with its number and a full stop (\"1. …\").\n\n"
    "Question: {question}"
)


def explanation_gaps(text: str) -> list[str]:
    """The gap sentences that can be answered without a source, in order."""
    gaps = []
    for match in _GAP.finditer(text or ""):
        sentence = match.group(0).strip(" -*•\t")
        # A standard's name ("IAS 16") is not a figure; what it covers can be explained.
        unnamed = _STANDARD_NAME.sub("", sentence)
        if sentence and not _NEEDS_SOURCE.search(unnamed) and sentence not in gaps:
            gaps.append(sentence)
    return gaps[:MAX_GAPS]


async def fill_explanation_gaps(text: str, question: str, complete: Callable[[str], Awaitable[str]],
                                provider_failure: str) -> tuple[str, bool]:
    """(answer with its explanation gaps filled, whether any was filled)."""
    gaps = explanation_gaps(text)
    if not gaps:
        return text, False
    try:
        reply = await complete(_PROMPT.format(gaps="\n".join(f"{i}. {g}" for i, g in enumerate(gaps, 1)),
                                              question=question)) or ""
    except Exception:  # noqa: BLE001 — a failed fill keeps the answer as it was
        return text, False
    if provider_failure in reply:
        return text, False
    filled = False
    for line in reply.splitlines():
        numbered = re.match(r"\s*(\d+)[.)]\s+(.+)", line)
        if not numbered:
            continue
        index, explanation = int(numbered.group(1)) - 1, numbered.group(2).strip()
        if 0 <= index < len(gaps) and len(explanation) >= 20 and not _FIGURE.search(explanation):
            text = _replace_sentence(text, gaps[index], f"{LABEL} {explanation}")
            filled = True
    return text, filled


def _replace_sentence(text: str, gap: str, replacement: str) -> str:
    """Replace the whole sentence the gap ends: replacing the gap alone left
    "Consequently, General explanation: …" and "Because General explanation:
    …" mid-sentence (22 Oct 2026)."""
    at = text.find(gap)
    if at < 0:
        return text
    line_start = text.rfind("\n", 0, at) + 1
    # A list marker or heading prefix on the line stays.
    prefix = re.match(r"[ \t]*(?:[-*•]|\d+[.)]|#{1,6})?[ \t]*", text[line_start:at]).end() + line_start
    ends = [m.end() for m in re.finditer(r"[.!?:](?:\s+|$)", text[prefix:at])]
    start = prefix + ends[-1] if ends else prefix
    return text[:start] + replacement + text[at + len(gap):]
