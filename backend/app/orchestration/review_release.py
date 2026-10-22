"""The warning shown with an answer that failed a check.

Product decision (2026-10-21): the reader always gets the answer. When a
check fails, the answer is shown with this warning and a copy still goes to
Review Tasks; "Response validation failed; escalated for review" with no
answer is no longer returned. The warning says, in plain words, what could
not be verified, so the reader knows what to check before relying on it.
"""
from __future__ import annotations

import re

_FIGURES = re.compile(r"unreconciled_figures:\s*(?P<figures>.+)", re.IGNORECASE)


def release_warning(failures: list[str]) -> str:
    reasons: list[str] = []
    for failure in failures:
        text = failure.lower()
        figures = _FIGURES.search(failure)
        if figures:
            reasons.append("these figures could not be matched to the sources: " + figures.group("figures").strip())
        elif "grounding check failed" in text or "authoritative evidence is unavailable" in text:
            reasons.append("no source was found to confirm it")
        elif "citation" in text or "contradicted or unsupported" in text or text.startswith("rejected:"):
            reasons.append("some statements could not be confirmed from the cited sources")
        elif "arithmetic" in text or "calculation" in text:
            reasons.append("a calculation could not be re-checked")
    reasons = list(dict.fromkeys(reasons)) or ["it did not pass every automatic check"]
    return ("Not fully verified: " + "; ".join(reasons) + ". Check the figures and facts before relying on "
            "this answer. A reviewer has also been notified.")
