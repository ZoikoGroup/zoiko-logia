"""Answers that reshape cited rules: a worked example, a checklist, common
mistakes, a version for a reviewer.

The citation rule ("every sentence must be stated by the evidence") made
these impossible: an example's entity and figures are made up by design, so
every follow-up chip ("Explain this with a grounded example", "Summarize this
as a checklist", "Show common mistakes") came back "The sources provided do
not establish an answer to this."

The rules an example applies are still cited and verified. Only the
scenario itself — the hypothetical entity and its figures, under an
"Illustrative example" heading — is exempt, and a sentence there that states
a rule, a rate or a standard is still checked like any other claim.
"""
from __future__ import annotations

import re

_DERIVED_REQUEST = re.compile(
    r"\b(?:examples?|illustrat\w*|scenario|case study|checklist|check\s+list|"
    r"common\s+(?:mistakes?|errors?|pitfalls?)|mistakes?\s+people|pitfalls?|"
    r"adapt\w*\b[^.?\n]{0,40}\bfor\b|for\s+an?\s+(?:reviewer|preparer|auditor|beginner|student|manager)|"
    r"step[- ]by[- ]step)\b",
    re.I,
)

ILLUSTRATION_HEADING = "Illustrative example (hypothetical figures)"
_ILLUSTRATION_TITLE = re.compile(r"^\W*illustrative\s+example\b", re.I)
_HEADING_LINE = re.compile(r"^\s*(?:#{1,6}\s+.+|(\*\*|__)[^*_]+\1\s*:?)\s*$")
# A sentence in the scenario that states a rule is still a claim.
_RULE_LANGUAGE = re.compile(
    r"\[REF-\d+\]|%|\b(?:IFRS|IAS|IFRIC|ISA|ASC|FRS|Ind\s?AS|Section)\s?\d|"
    r"\b(?:requires?|required|must|mandatory|permitted|prohibited|effective|supersed\w*|replac\w*|"
    r"rate|threshold|limit|deadline|due\s+date|penalt\w*|standard\s+states?|under\s+the\s+standard)\b",
    re.I,
)


def is_derived_output_request(question: str) -> bool:
    return bool(_DERIVED_REQUEST.search(question or ""))


def derived_output_instructions() -> str:
    return (
        "\n\nThe user asks for an example, checklist, common mistakes or a version for a role. "
        "Build it from the cited evidence; do not answer \"The sources provided do not state this\" "
        "merely because the evidence contains no ready-made example or checklist. "
        f"For an example, write it under the heading \"### {ILLUSTRATION_HEADING}\": a hypothetical "
        "entity and hypothetical amounts need no citation, but every sentence that applies or states a "
        "rule, rate, threshold, date or standard must end with the [REF-N] of the evidence that states "
        "that rule. Never put a real rate or threshold in the scenario without its citation. "
        "For a checklist, write each cited requirement as one check item ending with its [REF-N]. "
        "For common mistakes, describe each mistake as not following a cited requirement and state the "
        "correct requirement with its [REF-N]. For a role (reviewer, preparer, auditor), phrase each "
        "cited requirement as what that role checks, with its [REF-N]."
    )


def is_scenario_sentence(sentence: str) -> bool:
    """A sentence of a hypothetical example that states no rule."""
    return not _RULE_LANGUAGE.search(sentence or "")


def is_illustration_heading(heading: str) -> bool:
    return bool(_ILLUSTRATION_TITLE.search(heading or ""))


def without_scenarios(text: str) -> str:
    """The text without the scenario lines of its illustrative examples, for
    the figure check: a hypothetical £500,000 revenue is not an unsupported
    figure. Rule-stating lines in the example are kept and still checked."""
    kept: list[str] = []
    in_illustration = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if _HEADING_LINE.match(stripped):
            in_illustration = is_illustration_heading(stripped.strip("#*_: "))
            kept.append(line)
            continue
        if in_illustration and is_scenario_sentence(stripped):
            continue
        kept.append(line)
    return "\n".join(kept)
