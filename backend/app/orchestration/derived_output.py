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
# "Grounded example – a UK small business" too: without the requested heading
# every hypothetical figure of an example was removed as unverified (24 Oct 2026).
_ILLUSTRATION_TITLE = re.compile(r"\b(?:illustrative|grounded|worked|hypothetical)\s+example\b", re.I)
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


_KINDS = {
    "example": re.compile(r"\b(?:examples?|illustrat\w*|scenario|case study|worked)\b", re.I),
    "checklist": re.compile(r"\bcheck\s?list\b", re.I),
    "mistakes": re.compile(r"\b(?:common\s+(?:mistakes?|errors?|pitfalls?)|mistakes?\s+people|pitfalls?)\b", re.I),
    "role": re.compile(r"\badapt\w*\b[^.?\n]{0,40}\bfor\b|\bfor\s+an?\s+(?:reviewer|preparer|auditor|beginner|student|"
                       r"manager)\b", re.I),
    "steps": re.compile(r"\bstep[- ]by[- ]step\b", re.I),
}
_KIND_NAMES = {"example": "an example", "checklist": "a checklist", "mistakes": "common mistakes",
               "role": "a version for a role", "steps": "step-by-step guidance"}


def requested_kinds(question: str) -> list[str]:
    """The derived forms the question asks for. The instruction listed all of
    them whatever was asked, so a request for an example came back with a
    checklist, common mistakes and agent guidance too (24 Oct 2026). Only the
    chip's own request counts, not the earlier question in its context."""
    asked = (question or "").split(" Context: ")[0]
    return [kind for kind, pattern in _KINDS.items() if pattern.search(asked)] or ["example"]


def derived_output_instructions(question: str | None = None) -> str:
    kinds = requested_kinds(question) if question is not None else list(_KINDS)
    parts = [
        f"\n\nThe user asks for {' and '.join(_KIND_NAMES[kind] for kind in kinds)}. "
        "Build it from the cited evidence; do not answer \"The sources provided do not state this\" "
        "merely because the evidence contains no ready-made example or checklist."
    ]
    if "example" in kinds:
        parts.append(
            f"For an example, write it under the heading \"### {ILLUSTRATION_HEADING}\": a hypothetical "
            "entity and hypothetical amounts need no citation, but every sentence that applies or states a "
            "rule, rate, threshold, date or standard must end with the [REF-N] of the evidence that states "
            "that rule; when the evidence gives the rate you use (a VAT rate, say), cite it in the same "
            "sentence. Never put a real rate or threshold in the scenario without its citation; when the evidence "
            "does not give the rate you need, state the rate as an assumption for the illustration instead. "
            "For an example of a comparison, work the same scenario through each item compared; \"this "
            "comparison\" means the comparison in your previous answer, not a new one. Use only rules that bear on "
            "the example: leave out guidance the sources happen to contain on other matters (agents, avoidance, "
            "penalties) unless asked. "
            # A grounded VAT example contradicted its own explanation: input
            # VAT taken as the VAT-inclusive purchases, VAT counted in the
            # company's "tax burden", tax expense debited on payment (24 Oct 2026).
            "Keep the example consistent with the rules it illustrates and with your own explanation: say whether "
            "each amount includes tax and work any tax from that base; tax a business collects for the state is a "
            "liability, not its cost; record an expense or liability when it arises and its payment as a separate "
            "entry; every journal entry balances.")
    if "checklist" in kinds:
        parts.append("For a checklist, write each cited requirement as one check item ending with its [REF-N].")
    if "mistakes" in kinds:
        parts.append("For common mistakes, describe each mistake as not following a cited requirement and state "
                     "the correct requirement with its [REF-N].")
    if "role" in kinds:
        parts.append("For a role (reviewer, preparer, auditor), phrase each cited requirement as what that role "
                     "checks, with its [REF-N].")
    if "steps" in kinds:
        parts.append("For step-by-step guidance, write each cited requirement as one numbered step with its [REF-N].")
    if question is not None:
        missing = [_KIND_NAMES[kind] for kind in _KINDS if kind not in kinds and kind != "steps"]
        parts.append(f"Write only what is asked: do not add {', '.join(missing)}.")
    return " ".join(parts)


# Everything in _RULE_LANGUAGE except a bare "%" or "rate": a citation, a
# standard, an obligation, a threshold or a deadline.
_RULE_BEYOND_RATE = re.compile(
    r"\[REF-\d+\]|\b(?:IFRS|IAS|IFRIC|ISA|ASC|FRS|Ind\s?AS|Section)\s?\d|"
    r"\b(?:requires?|required|must|mandatory|permitted|prohibited|effective|supersed\w*|replac\w*|"
    r"threshold|limit|deadline|due\s+date|penalt\w*|standard\s+states?|under\s+the\s+standard)\b",
    re.I,
)
_ASSUMED = re.compile(r"\b(?:assum\w*|suppose|hypothetical(?:ly)?|for\s+(?:this\s+|the\s+)?illustration)\b", re.I)
_WORKED = re.compile(r"[\d)%]\s*[×x*÷/+−–-]\s*[£$€₹(]?\s*\d[^=\n]*=\s*[-−]?\s*[£$€₹]?\s*\d")
_STATES_ACTUAL = re.compile(r"\b(?:current|standard|statutory|actual|official|uk|india|us|is\s+\d)\b[^.\n]*\brate\b"
                            r"|\brate\b[^.\n]*\b(?:is|are|was|of)\s+\d", re.I)


def is_scenario_sentence(sentence: str) -> bool:
    """A sentence of a hypothetical example that states no rule.

    A rate stated as an assumption ("assume a 20% VAT rate for this
    illustration") and arithmetic on the example's own figures ("Output VAT
    = £90,000 × 20% = £18,000") are part of the example: the arithmetic is
    still checked separately. Removing them as rate claims emptied a VAT
    example's output, input and net tax (24 Oct 2026). A sentence that states
    an actual rate as fact, cites, or states a threshold or obligation is
    still a claim."""
    text = sentence or ""
    if not _RULE_LANGUAGE.search(text):
        return True
    if _RULE_BEYOND_RATE.search(text):
        return False
    if _ASSUMED.search(text):
        return True
    return bool(_WORKED.search(text)) and not _STATES_ACTUAL.search(text)


def is_illustration_heading(heading: str) -> bool:
    return bool(_ILLUSTRATION_TITLE.search(heading or ""))


def without_scenarios(text: str) -> str:
    """The text without the scenario lines of its illustrative examples, for
    the figure check: a hypothetical £500,000 revenue is not an unsupported
    figure. Rule-stating lines in the example are kept and still checked."""
    return _split_scenarios(text)[0]


def scenario_text(text: str) -> str:
    """The scenario lines of the text's illustrative examples: the example's
    own givens ("Turnover: £950,000"). A checked line of the example that works
    from them ("£950,000 × 20% = £190,000 [REF-3]") is checked against them as
    against the user's figures; without them the row failed and every line
    stating £950,000 was removed with it (24 Oct 2026)."""
    return _split_scenarios(text)[1]


def _split_scenarios(text: str) -> tuple[str, str]:
    kept: list[str] = []
    scenario: list[str] = []
    # The level of the example's heading while inside it: its own subheadings
    # ("Journal entries", "**Corporate income tax**") stay part of it until a
    # heading at its level or above; resetting at every heading took their
    # hypothetical figures out of the example (24 Oct 2026).
    illustration_level: int | None = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if _HEADING_LINE.match(stripped):
            level = len(stripped) - len(stripped.lstrip("#")) or 7
            if illustration_level is not None and level <= illustration_level:
                illustration_level = None
            if illustration_level is None and is_illustration_heading(stripped.strip("#*_: ")):
                illustration_level = level
            kept.append(line)
            continue
        if illustration_level is not None and is_scenario_sentence(stripped):
            scenario.append(line)
            continue
        kept.append(line)
    return "\n".join(kept), "\n".join(scenario)
