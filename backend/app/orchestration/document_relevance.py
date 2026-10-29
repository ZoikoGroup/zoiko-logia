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


def _matches(wanted: set[str], vocabulary: set[str]) -> int:
    """Question words found in the file, allowing a misspelling of a longer
    word: "assests" is "assets"."""
    from difflib import SequenceMatcher
    return sum(1 for word in wanted if word in vocabulary or (len(word) >= 5 and any(
        len(known) >= 5 and SequenceMatcher(None, word, known).ratio() >= 0.8 for known in vocabulary)))


# "Summarise the document", "explain the above table", "analyse this".
_DOCUMENT_REFERENCE = re.compile(
    r"\b(?:document|doc|file|attach\w*|upload\w*|spreadsheet|workbook|sheet|tab|table|rows?|columns?|"
    r"above|previous|earlier|same\s+data)\b"
    r"|\b(?:summari[sz]e|analy[sz]e|review|check|explain|describe|translate)\s+(?:this|it|that|them|these)\b",
    re.IGNORECASE)
# Question words that say nothing about a file's content.
_GENERAL = frozenset((
    "what", "explain", "about", "define", "definition", "meaning", "mean", "difference", "between", "should",
    "would", "could", "where", "when", "there", "their", "under", "current", "latest", "rule", "rules", "tell",
    "know", "does", "work", "works", "example", "examples", "today", "news", "india", "united", "kingdom",
    # A bare follow-up to the previous answer ("Why?", "Explain more").
    "why", "how", "more", "again", "yes", "okay", "thanks", "continue", "detail", "details", "elaborate",
))


# An amount the question states itself: "$2 million", "£12,000", "4,500".
# Small counts ("top 5", "four sentences") and codes ("E012", "FY2025") are
# not figures of their own.
_OWN_FIGURE = re.compile(
    r"(?<![\w.])(?P<currency>[$£€₹])?\s?(?P<number>\d[\d,]*(?:\.\d+)?)\s?(?P<scale>million|billion|m\b|bn\b|k\b)?",
    re.IGNORECASE)
_SCALE = {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "k": 1e3}


def _brings_its_own_figures(query: str, sources: list[WebSource]) -> bool:
    """The question states an amount the files do not contain: it is a new
    question, not about them. "When should my company recognise this $2
    million contract revenue?" and "the journal entry for a $12,000 invoice",
    asked after attaching a statement PDF, were answered from the PDF (an
    invented quarterly allocation; "insufficient evidence")."""
    content = re.sub(r"(?<=\d),(?=\d)", "", " ".join(source.snippet or "" for source in sources))
    own = []
    for match in _OWN_FIGURE.finditer(query or ""):
        digits = match.group("number").replace(",", "")
        if not (match.group("currency") or match.group("scale") or len(digits.split(".")[0]) >= 4):
            continue
        scale = _SCALE.get((match.group("scale") or "").lower(), 1)
        value = float(digits) * scale
        # "$2 million" is 2000000, never the bare 2 ("Note 2."); a file in
        # thousands states it as 2,000.
        written = ({f"{value:.0f}"} if match.group("scale") else {digits}) | (
            {f"{value / 1000:.0f}"} if value >= 1e6 else set())
        own.append(written)
    return bool(own) and not any(any(re.search(rf"(?<![\d.]){re.escape(w)}(?![\d])", content) for w in written)
                                 for written in own)


def question_is_about_documents(query: str, sources: list[WebSource]) -> bool:
    """Whether a follow-up with no new upload is about the chat's files. One
    that is not ("What is IPR?" after a VAT file) is answered as a new
    question, not from the files. When unsure, the files are kept."""
    if _DOCUMENT_REFERENCE.search(query or ""):
        return True
    if _brings_its_own_figures(query, sources):
        return False
    wanted = _terms(query) - _GENERAL
    if not wanted:
        return True      # "why?", "and the total?": nothing new to ask about
    by_file: dict[str, list[WebSource]] = {}
    for source in sources:
        by_file.setdefault(source.source_id or _file(source), []).append(source)
    if any(_matches(wanted, _vocabulary(group)) for group in by_file.values()):
        return True
    # A name or term in the file's rows: "What did Harbour Kitchens pay?"
    content = " ".join((source.snippet or "").lower() for source in sources)
    return any(len(word) >= 4 and word in content for word in wanted)


def documents_for_question(query: str, sources: list[WebSource]) -> set[str] | None:
    """The source_ids of the files the question is about, or None to keep
    every file (one file, no file matching, or several matching equally)."""
    by_file: dict[str, list[WebSource]] = {}
    for source in sources:
        by_file.setdefault(source.source_id or _file(source), []).append(source)
    if len(by_file) < 2:
        return None
    wanted = _terms(query)
    scores = {key: _matches(wanted, _vocabulary(group)) for key, group in by_file.items()}
    best = max(scores.values())
    keep = {key for key, score in scores.items() if score == best}
    if best == 0 or len(keep) == len(scores):
        return None
    return keep
