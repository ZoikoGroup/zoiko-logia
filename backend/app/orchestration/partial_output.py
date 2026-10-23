"""What can be shown of an answer the model did not finish.

The standard path used to discard a response cut off at the output limit,
however much of it was complete: three questions on 22 Oct 2026 came back
"Not answered — please try again" after writing most of their tables. The
agent path already kept such text as a labelled partial answer.

Only complete statements survive: the text is cut back to its last finished
sentence or table row, so an unfinished calculation ("Total = 153,"), an open
code block, a half-written table row or a heading with nothing under it is
never shown as if final. What remains still goes through every release check,
and the caller marks the answer incomplete.
"""
from __future__ import annotations

import re

# Less than this of finished prose is not worth showing as an answer.
MIN_USEFUL_CHARS = 160
STOPPED_NOTE = "_The response stopped here before it was finished._"

_SENTENCE_END = re.compile(r"[.!?…:)\]*_]$|[.!?]['\"”’)]$")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S.*|(\*\*|__)[^*_]+\1:?)\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(row: str) -> int:
    return row.strip().strip("|").count("|") + 1


def _complete_table_row(line: str, lines_before: list[str]) -> bool:
    """A row with as many cells as its table's header, closed by a pipe."""
    if not line.rstrip().endswith("|"):
        return False
    header = None
    for earlier in reversed(lines_before):
        if not earlier.lstrip().startswith("|"):
            break
        header = earlier
    return header is None or _cells(line) >= _cells(header)


def _finished(line: str, lines_before: list[str]) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("|"):
        return _TABLE_SEPARATOR.match(stripped) is None and _complete_table_row(stripped, lines_before)
    return bool(_SENTENCE_END.search(stripped))


def usable_partial(text: str) -> str:
    """The finished part of a cut-off answer, marked as stopped, or "" when too
    little of it is finished to be worth showing."""
    lines = (text or "").rstrip().splitlines()
    # An unclosed code block (a chart, a formula) is dropped from its opening.
    fences = [i for i, line in enumerate(lines) if line.strip().startswith("```")]
    if len(fences) % 2:
        lines = lines[:fences[-1]]
    # The last line is where the limit fell: keep its finished sentences only.
    if lines and not _finished(lines[-1], lines[:-1]) and not lines[-1].lstrip().startswith("|"):
        last = lines[-1]
        ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", last)]
        kept = last[:ends[-1]] if ends else ""
        # "3. Deferred revenue is 27,000 (" keeps no sentence, only its number.
        lines[-1] = "" if re.fullmatch(r"\s*(?:[-*•]|\(?\w{1,3}[.)])?\s*", kept) else kept
    while lines and (not _finished(lines[-1], lines[:-1]) or not lines[-1].strip()
                     or _HEADING.match(lines[-1]) or _TABLE_SEPARATOR.match(lines[-1].strip())):
        lines.pop()
    substantive = "".join(line.strip() for line in lines if line.strip() and not _HEADING.match(line))
    if len(substantive) < MIN_USEFUL_CHARS:
        return ""
    return "\n".join(lines) + "\n\n" + STOPPED_NOTE
