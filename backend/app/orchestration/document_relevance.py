"""Which of a chat's attached files a follow-up question is about.

A follow-up restores every file attached earlier in the chat. With a sales
file, a payroll register and a fixed-asset register attached, "Show the net
book value of each asset category" sent all three, with the verified figures
of each, and went over the model's request-size limit; only the fixed-asset
register was needed.

A file is kept when it matches the question best by its file name and column
names. When no file matches, or the question names no file in particular,
every file is kept, as before.
"""
from __future__ import annotations

import re

from app.orchestration.websearch import WebSource

_WORD = re.compile(r"[a-z]{3,}")
_STOP = frozenset((
    "the", "and", "for", "from", "with", "this", "that", "these", "those", "each", "every", "all", "per", "show",
    "give", "what", "which", "how", "are", "was", "were", "has", "have", "please", "prepare", "calculate", "list",
    "summary", "summarise", "summarize", "total", "totals", "amount", "amounts", "value", "values", "document",
    "documents", "file", "files", "attached", "above", "table", "sheet", "data", "chart", "bar", "pie", "line",
    "graph", "month", "monthly", "year", "period", "into", "using", "based", "also", "make", "generate", "csv",
    "xlsx", "kriton", "test",
))
_DOC_TITLE = re.compile(r"^(?P<file>.*?)\s+—\s+.+$")


def _terms(text: str) -> set[str]:
    words = _WORD.findall((text or "").lower().replace("_", " ").replace("-", " "))
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words if w not in _STOP}


def _file(source: WebSource) -> str:
    match = _DOC_TITLE.match(source.title or "")
    return match.group("file") if match else (source.title or "")


def _vocabulary(sources: list[WebSource]) -> set[str]:
    """A file's name and the header row of each extracted table."""
    words = _terms(_file(sources[0]))
    for source in sources:
        for line in (source.snippet or "").splitlines()[:3]:
            if "\t" in line:
                words |= _terms(line)
    return words


def documents_for_question(query: str, sources: list[WebSource]) -> set[str] | None:
    """The source_ids of the files the question is about, or None to keep
    every file (one file, no file matching, or several matching equally)."""
    by_file: dict[str, list[WebSource]] = {}
    for source in sources:
        by_file.setdefault(source.source_id or _file(source), []).append(source)
    if len(by_file) < 2:
        return None
    wanted = _terms(query)
    scores = {key: len(wanted & _vocabulary(group)) for key, group in by_file.items()}
    best = max(scores.values())
    keep = {key for key, score in scores.items() if score == best}
    if best == 0 or len(keep) == len(scores):
        return None
    return keep
