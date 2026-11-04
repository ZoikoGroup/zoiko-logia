"""Validation findings and their resolution (Task Contract, Stage D).

A validator reports what it found as a ValidationFinding: the category, the
rule, the figure or statement, the evidence and the action it proposes. It
does not remove or rewrite the answer itself. resolve() decides, with fixed
precedence rules, which findings stand; only those reach the code that
removes statements or adds notes, so one check cannot undo what another
verified (architecture assessment, 29 Oct 2026, defect classes 2, 6 and 7).

Precedence rules (in order):
  P1 provenance before re-check: a stated figure equal to a value the
     calculator verified (the deterministic calculation's outputs and
     schedule, or the agent's own calculate results) is not disproved by an
     arithmetic re-check of the model's written working. "$173,255.28" (the
     lease calculator's result) was removed because the model showed a
     factor rounded to six places (29 Oct 2026).
  P2 input precision: the arithmetic validator judges a result within the
     rounding its own displayed intermediates carry (calculation_service);
     that is evidence on the finding, not a separate exception.
  P3 proportionate removal: a finding about a statement removes that
     statement; the whole answer is withdrawn only when nothing of substance
     is left. One sentence judged to be from another framework replaced an
     entire three-part audit answer (29 Oct 2026).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

Category = Literal[
    "input_validity", "numerical_correctness", "numerical_provenance", "accounting_treatment",
    "deliverable_completeness", "case_integrity", "visualization_suitability", "final_disposition",
]


class ValidationFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: Category
    rule: str
    status: Literal["fail", "warn", "pass"] = "fail"
    action: Literal["remove_statement", "flag", "note", "none"] = "flag"
    # The figure as stated and the value the validator computed, when numerical.
    stated: Optional[Decimal] = None
    expected: Optional[Decimal] = None
    expression: str = ""
    tolerance: Optional[Decimal] = None
    # The exact text the existing pipeline uses for this failure (unchanged
    # for every existing consumer: correction prompts, warnings, removal).
    evidence: str = ""


class Resolution(BaseModel):
    standing: list[ValidationFinding] = Field(default_factory=list)
    overridden: list[tuple[ValidationFinding, str]] = Field(default_factory=list)

    def failure_texts(self) -> list[str]:
        return [finding.evidence for finding in self.standing if finding.status == "fail"]


def _matches_verified(value: Decimal, tolerance: Decimal | None, verified: Iterable[Decimal]) -> bool:
    # The precision the figure is stated to: "$173,255.28" against 173255.280635.
    allowance = max(tolerance or Decimal(0), Decimal("0.005"))
    return any(abs(value - item) <= allowance for item in verified)


def resolve(findings: list[ValidationFinding], *, verified_values: Iterable = ()) -> Resolution:
    """Which findings stand, applying the precedence rules above."""
    verified = []
    for item in verified_values or ():
        try:
            verified.append(Decimal(str(item)))
        except Exception:  # noqa: BLE001 — a value that is not a number is not evidence
            continue
    resolution = Resolution()
    for finding in findings:
        if (finding.rule == "arithmetic_mismatch" and finding.stated is not None and verified
                and _matches_verified(finding.stated, finding.tolerance, verified)):
            resolution.overridden.append((finding, "P1: the stated figure is the calculator's verified result"))
            continue
        resolution.standing.append(finding)
    return resolution


def remove_statements(answer: str, findings: list[ValidationFinding], note: str) -> str:
    """P3: the answer without the statements the standing findings name, each
    replaced by the note; "" when nothing of substance would remain (the
    caller then withdraws the answer, as before)."""
    from app.orchestration.claim_verification import is_removal_note, remove_claims
    statements = list(dict.fromkeys(f.expression for f in findings if f.action == "remove_statement" and f.expression))
    if not statements:
        return answer
    cleaned = remove_claims(answer, statements, note)
    substantive = [line for line in cleaned.splitlines()
                   if line.strip() and not line.lstrip().startswith("#") and not is_removal_note(line)
                   and not re.fullmatch(r"[\s|:\-]+", line) and note not in line]
    return cleaned if substantive else ""


_WORD = re.compile(r"[A-Za-z]{4,}")


def answered_as_general_explanation(part: str, final_text: str) -> bool:
    """A requested part the final answer gives as a labelled general
    explanation: a "General explanation:" line that, with the heading just
    above it, names the part (most of its words). Completeness is judged on
    the answer the reader gets, after every step that changed it."""
    from app.orchestration.gap_filler import LABEL
    words = {word.lower() for word in _WORD.findall(part or "")}
    if not words:
        return False
    lines = (final_text or "").splitlines()
    for index, line in enumerate(lines):
        if LABEL.lower() not in line.lower():
            continue
        nearby = " ".join(lines[max(0, index - 2): index + 1]).lower()
        if 2 * sum(word in nearby for word in words) > len(words):    # more than half of the part's words
            return True
    return False


def verified_values_from(calculation_result=None, receipts: Iterable[dict] | None = None) -> list[Decimal]:
    """The values the deterministic calculator or the agent's calculate tool
    produced: the evidence P1 relies on."""
    values: list[Decimal] = []
    if calculation_result is not None and getattr(calculation_result, "status", "") == "success":
        values += [item.value for item in getattr(calculation_result, "outputs", []) or [] if item.value is not None]
        # The schedule's cells exactly as calculated (no rescaling).
        for table in getattr(calculation_result, "tables", None) or []:
            for row in table.get("rows", []):
                values += [Decimal(number.replace(",", "")) for number in _NUMBER.findall(" ".join(str(cell) for cell in row))]
    for receipt in receipts or ():
        for key in ("result", "rounded"):
            try:
                values.append(Decimal(str(receipt.get(key))))
            except Exception:  # noqa: BLE001
                continue
    return values


# ── Stage F: deliverable completeness against the Task Contract ──────────────
# Each output the contract records (task_contract.requested_outputs) is looked
# for in the final answer the reader gets. An amount is present when a line
# (or table row) names it, its head noun and, where it has any, one of its
# modifiers, with a figure on that line; a journal entry needs debit and
# credit sides; a schedule a table of three or more rows; a chart a visual; a
# citation a provision reference. Each missing output is a finding with
# action "note"; the caller adds the existing "Incomplete answer" note.
# Deterministic; reports presence only, never correctness.

_STOP = {"the", "a", "an", "of", "for", "on", "at", "in", "to", "and", "per", "by", "from", "after", "before", "over",
         "under", "using", "with", "as", "year", "years", "full", "each", "its", "their", "this", "that", "total"}
_PREPOSITION = re.compile(r"\s+(?:after|at|for|of|on|in|over|under|per|by|using|from|as\s+at|to|with|before|between)\s+", re.I)
_SYNONYMS = {
    "carrying amount": ("net book value", "nbv", "book value", "written down value", "wdv", "carrying value"),
    "depreciation": ("depreciation charge", "depreciation expense"),
    "margin": ("margin", "gross margin", "profit margin"),
    "right-of-use asset": ("rou asset", "right of use asset"),
    "liability": ("liability", "obligation"),
    "unearned profit": ("unrealised profit", "unrealized profit"),
}
_FIGURE = re.compile(r"\d")
# A head noun this general needs one of the output's other words beside it
# ("carrying amount", not any "amount"); a specific one ("depreciation",
# "SGST", "tax") is enough with a figure on its line.
_GENERAL = {"amount", "value", "total", "cost", "costs", "charge", "balance", "expense", "liability", "asset",
            "rate", "profit", "loss", "income", "figure", "position", "impact", "effect"}
# The answer says why the chart cannot be drawn (answer_coverage's own test).
_CHART_DECLINED = re.compile(r"chart[^.\n]{0,70}(?:need|cannot|could not|not available|not establish|not support|requires)"
                             r"|(?:need|cannot)[^.\n]{0,70}chart", re.I)
_DEBIT = re.compile(r"\b(?:dr|debit)\b", re.I)
_CREDIT = re.compile(r"\b(?:cr|credit)\b", re.I)
_PROVISION = re.compile(r"\b(?:section|s\.|sec\.|paragraph|para\.?|article|regulation|rule|schedule)\s*\d"
                        r"|\b(?:IAS|IFRS|ASC|FRS|Ind\s?AS|ISA)\s*\d", re.I)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _stem(word: str) -> str:
    return word.lower()[:6]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z-]*", text.lower()) if w not in _STOP]


def _amount_present(name: str, lines: list[str]) -> bool:
    # "discount or premium": either is the output.
    if re.search(r"\s+or\s+", name):
        return any(_amount_present(alt, lines) for alt in re.split(r"\s+or\s+", name) if alt.strip())
    head = _PREPOSITION.split(name, maxsplit=1)[0]
    words = _words(head) or _words(name)
    if not words:
        return True
    # The head noun, with any other word of the name ("profit to eliminate").
    noun = words[-1]
    modifiers = [w for w in _words(name) if w != noun]
    phrase = " ".join(words)
    alternatives = [alt for key, alts in _SYNONYMS.items() if key in phrase for alt in alts]
    for line in lines:
        if not _FIGURE.search(line):
            continue
        low = line.lower()
        if any(alt in low for alt in alternatives):
            return True
        stems = {_stem(w) for w in re.findall(r"[a-z][a-z-]*", low)}
        stems |= {_stem(part) for w in re.findall(r"[a-z][a-z-]*", low) for part in w.split("-")}
        if _stem(noun) in stems and (noun not in _GENERAL or not modifiers or any(_stem(m) in stems for m in modifiers)):
            return True
    return False


def deliverable_findings(outputs, answer: str, *, has_visual: bool = False) -> list[ValidationFinding]:
    """One finding for each requested output the answer does not contain."""
    text = answer or ""
    lines = [line for line in text.splitlines() if line.strip()]
    findings = []
    for output in outputs or ():
        kind, name = output.kind, output.name
        if kind == "amount":
            present = _amount_present(name, lines)
        elif kind == "journal_entry":
            present = bool(_DEBIT.search(text) and _CREDIT.search(text))
        elif kind == "schedule":
            present = sum(bool(_TABLE_ROW.match(line)) for line in lines) >= 4    # header, rule, 2+ rows
        elif kind == "chart":
            present = has_visual or "```chart" in text or bool(_CHART_DECLINED.search(text))
        elif kind == "citation":
            present = bool(_PROVISION.search(text))
        else:
            continue
        if not present:
            findings.append(ValidationFinding(category="deliverable_completeness", rule=f"missing_{kind}", action="note",
                                              expression=name, evidence=f"Requested {name} is not in the answer."))
    return findings
