"""The warning shown with an answer that failed a check.

Product decision (2026-10-21): the reader always gets the answer. When a
check fails, the answer is shown with this warning and a copy still goes to
Review Tasks; "Response validation failed; escalated for review" with no
answer is no longer returned. The warning says, in plain words, what could
not be verified, so the reader knows what to check before relying on it.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_FIGURES = re.compile(r"unreconciled_figures:\s*(?P<figures>.+)", re.IGNORECASE)
# The calculator's proof that a stated figure is wrong (calculation_service).
_MISMATCH = re.compile(
    r"Calculation mismatch:\s*(?P<expression>.+?)\s+equals\s+(?P<expected>-?[\d.,]+),\s+not\s+(?P<stated>-?[\d.,]+)\.",
    re.IGNORECASE,
)


def remove_disproved_figures(answer: str, failures: list[str]) -> tuple[str, list[str]]:
    """The answer without the statements stating a figure the calculator
    proved wrong, and a note for each naming the verified result.

    Showing the answer with a warning is right for what could not be
    verified; it is not right for what is known to be false. "£780,000 ÷ 0.55
    = £1,560,000" was released, marked complete, beside a warning that "a
    calculation could not be re-checked". Only the disproved statements go;
    the rest of the answer stays."""
    from app.orchestration.claim_verification import FIGURES_REMOVED_NOTE, remove_claims
    from app.orchestration.figure_reconciliation import material_figures, statements_with_figures

    shown_figures = material_figures(answer or "")
    disproved: list[str] = []
    notes: list[str] = []
    for failure in failures:
        match = _MISMATCH.search(failure)
        if not match:
            continue
        try:
            stated = Decimal(match.group("stated").replace(",", ""))
        except InvalidOperation:
            continue
        hits = [shown for shown, value in shown_figures if abs(Decimal(str(value)) - stated) < Decimal("0.005")]
        if hits:
            disproved.extend(hits)
            notes.append(f"{hits[0]} ({match.group('expression')} equals {match.group('expected')})")
    if not disproved:
        return answer, []
    statements = statements_with_figures(answer, list(dict.fromkeys(disproved)))
    cleaned = remove_claims(answer, statements, FIGURES_REMOVED_NOTE)
    substantive = [line for line in cleaned.splitlines()
                   if line.strip() and not line.lstrip().startswith("#") and FIGURES_REMOVED_NOTE not in line
                   and not re.fullmatch(r"[\s|:\-]+", line)]
    # Headings over removal notes are not an answer: the caller sends it to review.
    return (cleaned if substantive else ""), notes


def release_warning(failures: list[str], *, disproved_removed: bool = False) -> str:
    reasons: list[str] = []
    for failure in failures:
        text = failure.lower()
        figures = _FIGURES.search(failure)
        if disproved_removed and _MISMATCH.search(failure):
            reasons.append("a figure that did not match its own calculation was removed")
        elif figures:
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
