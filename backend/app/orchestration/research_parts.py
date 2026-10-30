"""Bounded search subjects for labelled claims and comparison-table rows.

Keep the original material for composition. These subjects only guide
retrieval; a matching search result is never proof that a claim is true.
"""
from __future__ import annotations

import re

MAX_PARTS = 8
_LABELLED = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.{3,100}?)\s*:\s*(.+)$")
_SEPARATOR = re.compile(r"^[\s|:\-]+$")


def structured_research_parts(query: str) -> list[str]:
    text = (query or "").rsplit(" Context: ", 1)[-1].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parts: list[str] = []
    table_header_seen = False
    context = ""
    for line in lines:
        match = _LABELLED.match(line)
        if match:
            parts.append(" ".join(match.groups()))
        elif "\t" in line or (line.startswith("|") and line.endswith("|")):
            if _SEPARATOR.fullmatch(line):
                continue
            cells = [cell.strip() for cell in re.split(r"\t|\|", line) if cell.strip()]
            if len(cells) < 2:
                continue
            if not table_header_seen:
                table_header_seen = True
                continue
            parts.append(" ".join(cells))
        elif not parts and not context:
            # Retain the shared subject (e.g. global tax audits) for short
            # labels such as "Persistent subsidiary losses".
            context = line[:180]
    unique = list(dict.fromkeys(" ".join(part.replace("**", "").split())[:420] for part in parts))
    if len(unique) < 2:
        return []
    return [f"{context} {part}".strip() for part in unique[:MAX_PARTS]]


def targeted_retry_query(subject: str) -> str:
    """A second query using the subject's keywords, not the same sentence."""
    words = re.findall(r"[\w'-]+", subject, re.UNICODE)
    stop = {"the", "a", "an", "is", "are", "was", "were", "this", "that", "these", "whether", "check"}
    keywords = " ".join(word for word in words if word.lower() not in stop)[:360]
    return f"{keywords} official guidance"
