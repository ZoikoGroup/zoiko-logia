"""A general explanation for a concept question the sources do not cover.

"Give me the difference between audit and accounting" searched the auditing
standard setter, found pages on auditing accounting estimates, and the answer
was "Not answered — insufficient evidence". A basic concept needs no source
to be explained correctly, and the reader got nothing.

Only for a concept question (what is / define / explain / difference / types
of …) that names no figure, rate, rule or live data, asks nothing about an
attached file, and does not need authoritative evidence. The explanation must
state no figure, rate, threshold, date or law section (checked here, and the
text is discarded if it does), is labelled as a general explanation, and the
official sources to check are still listed (source_guarantee.py).
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

from app.orchestration.calculation_service import needs_lookup
from app.orchestration.verification_service import requires_authoritative_evidence

GENERAL_NOTE = ("General explanation from established accounting knowledge: the retrieved sources did not "
                "cover this question, so no source is cited. Check an official source before relying on it.")

_CONCEPT = re.compile(
    r"\b(?:what\s+(?:is|are|does)|what's|define|definition|meaning|explain|describe|"
    r"differences?|distinguish|difference\s+between|compare|vs\.?|versus|types?\s+of|kinds\s+of|"
    r"purpose\s+of|role\s+of|objectives?\s+of|features?\s+of|advantages|importance\s+of|how\s+does|"
    # "Show how a draft journal entry becomes an approved posted journal
    # entry" (QA case E02) got only "the sources do not contain this".
    r"show\s+how|how\s+an?\s+\w[\w\s-]*?\s+becomes)\b",
    re.IGNORECASE,
)
_PROMPT = (
    "You are Kriton, an assistant for accounting, tax, audit, payroll and finance. The retrieved sources "
    "did not cover the question below. Answer it as a clear, correct general explanation from established "
    "accounting knowledge: a short opening sentence, then short headings, bullet points or a comparison "
    "table where that helps. Do not state any figure, percentage, rate, threshold, amount, date, deadline "
    "or section of a law. Do not cite sources and do not write [REF-n] markers.\n\nQuestion: {question}"
)
# A figure the explanation must not contain: a percentage, a currency amount,
# or a number of three or more digits (a threshold, a section, a year).
_FIGURE = re.compile(r"%|[£$€₹¥]|\b\d{3,}\b|\[REF-", re.IGNORECASE)


def is_concept_question(query: str, *, has_documents: bool, uses_live_data: bool) -> bool:
    text = (query or "").strip()
    return (
        bool(text) and len(text) <= 300 and bool(_CONCEPT.search(text)) and not re.search(r"\d", text)
        and not has_documents and not uses_live_data
        and not requires_authoritative_evidence(text) and not needs_lookup(text)
    )


async def general_explanation(question: str, complete: Callable[[str], Awaitable[str]], provider_failure: str) -> str:
    """The explanation, or "" when the model failed or stated a figure."""
    try:
        text = (await complete(_PROMPT.format(question=question))) or ""
    except Exception:  # noqa: BLE001 — a failed fallback keeps the original answer
        return ""
    text = text.strip()
    if len(text) < 40 or provider_failure in text or _FIGURE.search(text):
        return ""
    return text
