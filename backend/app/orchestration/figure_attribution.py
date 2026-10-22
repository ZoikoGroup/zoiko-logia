"""A verified figure in the wrong period or scenario.

figure_reconciliation checks that every figure traces to the user's facts, a
source or the calculator. That is not enough when the facts cover two
periods (this year and the previous year) or two scenarios (the original
forecast and a revised one): the prior year's £660,000 cost of goods sold is
a verified number, and still wrong in the current-year column.

Each of the user's figures is tagged with the period or scenario it was
stated for, and a calculator result inherits its operands' tags. A figure
shown in a context (a table column, or a sentence naming exactly one period)
whose only provenance is a different period or scenario is misattributed.
Figures with no tag, or tagged for both, are never flagged: this only
catches a figure that demonstrably belongs elsewhere.
"""
from __future__ import annotations

import re

from app.orchestration.figure_reconciliation import (
    _NUMBER, _amount, _operand_tolerance, _readable, _statements, material_figures,
)

CURRENT, PRIOR, ORIGINAL, REVISED = "current period", "prior period", "original scenario", "revised scenario"

_CURRENT_CUE = re.compile(r"\b(?:current|this)\s+(?:financial\s+|fiscal\s+|accounting\s+)?(?:year|period|quarter|month)\b"
                          r"|\b(?:financial|fiscal)\s+year\s+(?:ended|ending)\b|\bthis\s+year\b", re.I)
_PRIOR_CUE = re.compile(r"\b(?:previous|prior|last|preceding|comparative)\s+(?:financial\s+|fiscal\s+|accounting\s+)?"
                        r"(?:year|period|quarter|month)\b|\blast\s+year\b|\bprior[- ]year\b", re.I)
_ORIGINAL_HEADER = re.compile(r"\b(?:original|base(?:line)?|before|existing|initial)\b", re.I)
_REVISED_HEADER = re.compile(r"\b(?:revised|new|scenario|after|adjusted|updated|proposed)\b", re.I)
_CURRENT_HEADER = re.compile(r"\b(?:current|this\s+year|actual)\b", re.I)
_PRIOR_HEADER = re.compile(r"\b(?:previous|prior|last\s+year|comparative)\b", re.I)
_CHANGE_HEADER = re.compile(r"\b(?:change|variance|difference|movement|yoy|growth|delta|%)\b", re.I)
_CHANGE_VERB = re.compile(r"\b(?:increase[sd]?|decrease[sd]?|rise[sn]?|rose|fall[sn]?|fell|grow[sn]?|cut|reduce[sd]?|"
                          r"change[sd]?|goes up|go up|drop[s]?|becomes?)\b", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _revises_prior_task(question):
    # Having chat history does not make every new task a revised scenario.
    # In a reconciliation, "Original amount" and "Adjusted amount" are
    # balance stages of the current task, not evidence of a prior task.
    return bool(_CHANGE_VERB.search(question) or re.search(
        r'\b(?:recalculate|revised|updated|what if|correct only|set only)\b',question,re.I))


def tagged_facts(question: str, earlier_user_turns: list[str],
                 earlier_answers: list[str] | None = None) -> list[tuple[float, str]]:
    """(amount, tag) for each figure the user stated. Earlier turns are the
    original scenario when the current turn revises it, and so are the figures
    of the earlier answers (the original scenario's released results, such as
    its £540,000 operating profit); within one message, a period cue tags the
    lines that follow it until the next cue."""
    if not _revises_prior_task(question):
        earlier_user_turns=[]
        earlier_answers=[]
    tagged: list[tuple[float, str]] = []
    for turn in [*earlier_user_turns, *((earlier_answers or []) if earlier_user_turns else [])]:
        tagged += [(amount, ORIGINAL) for amount in _amounts(turn)]
    if earlier_user_turns:
        tagged += [(amount, REVISED) for amount in _amounts(question)]
        return tagged
    tag = None
    for line in _readable(question).splitlines():
        prior, current = _PRIOR_CUE.search(line), _CURRENT_CUE.search(line)
        if prior and not current:
            tag = PRIOR
        elif current and not prior:
            tag = CURRENT
        elif prior and current:
            tag = None                                   # a line about both periods tags nothing
        if tag:
            tagged += [(amount, tag) for amount in _amounts(line)]
    return tagged


def changed_items(question: str) -> list[str]:
    """Items the current turn changes: "revenue increases by 12%", "fixed
    operating costs increase by £60,000" → ["revenue", "fixed operating costs"]."""
    items = []
    for clause in re.split(r"[,.;]|\band\b|\bthen\b", question or "", flags=re.I):
        verb = _CHANGE_VERB.search(clause)
        if not verb:
            continue
        before = clause[:verb.start()]
        words = re.findall(r"[a-z][a-z-]+", before.lower())
        stop = {"the", "a", "an", "our", "where", "if", "when", "now", "model", "scenario", "in", "which", "that",
                "by", "of", "stays", "remains", "would", "will", "calculate", "what"}
        label = [word for word in words[-3:] if word not in stop]
        if label:
            items.append(" ".join(label))
    return items


_GENERIC_WORDS = {"revised", "new", "original", "base", "baseline", "scenario", "total", "amount", "the", "of",
                  "and", "for", "in", "a", "an", "value", "figure", "current", "updated", "adjusted"}


def _label_words(label: str) -> frozenset[str]:
    return frozenset(word for word in re.findall(r"[a-z][a-z-]+", (label or "").lower()) if word not in _GENERIC_WORDS)


def _receipt_result(receipt: dict) -> float:
    try:
        return float(str(receipt.get("result", "")).replace(",", ""))
    except ValueError:
        return float("nan")


def _amounts(text: str) -> list[float]:
    return [_amount(shown, value) for shown, value in material_figures(_readable(text))]


def provenance(value: float, facts: list[tuple[float, str]], receipts: list[dict], _depth: int = 0) -> set[str]:
    """The tags of the user's figures equal to `value`, or of the operands of
    a calculator result equal to it (a revised operand makes it revised)."""
    tolerance = _operand_tolerance(value)
    tags = {tag for amount, tag in facts if abs(abs(amount) - abs(value)) <= tolerance}
    if tags:
        return tags
    for receipt in receipts or []:
        try:
            result = float(str(receipt.get("result", "")).replace(",", ""))
        except ValueError:
            continue
        if abs(abs(result) - abs(value)) > max(tolerance, 0.006):
            continue
        operand_tags: set[str] = set()
        untraced = False
        for token in _NUMBER.findall(str(receipt.get("expression", ""))):
            operand = float(token.replace(",", ""))
            tags_here = {tag for amount, tag in facts
                         if abs(abs(amount) - abs(operand)) <= _operand_tolerance(operand)
                         or abs(abs(amount) / 100 - abs(operand)) <= 1e-9}
            if not tags_here and _depth < 3 and operand not in (0, 1, 2, 3, 4, 12, 100):
                # An earlier calculation's result (2,688,000 in "2688000 × 0.45")
                # carries that calculation's context.
                others = [r for r in receipts if r is not receipt]
                tags_here = provenance(operand, facts, others, _depth + 1) if others else set()
            untraced |= not tags_here and operand not in (0, 1, 2, 3, 4, 12, 100)
            if len(tags_here) == 1:                      # stated in both ("stays at 45%"): neutral
                operand_tags |= tags_here
        if REVISED in operand_tags or (ORIGINAL in operand_tags and untraced):
            # Anything the revision brings in (60,000, or 1.12 for "+12%")
            # makes the result the revision's; only all-original operands
            # keep it original.
            return {REVISED}
        return operand_tags if len(operand_tags) == 1 and not untraced else set()
    return _derived_tags(value, facts)


def _derived_tags(value: float, facts: list[tuple[float, str]]) -> set[str]:
    """The one context whose facts alone produce `value` in one step:
    £1,080,000 = £2,400,000 × 45% (original), £440,000 = £1,100,000 − £660,000
    (prior year). Empty when no context does, or more than one does."""
    from app.orchestration.figure_reconciliation import _one_step_from
    tolerance = _operand_tolerance(value)
    tags = set()
    for tag in {tag for _, tag in facts}:
        own = [amount for amount, t in facts if t == tag]
        own += [amount / 100 for amount in own if abs(amount) <= 100]       # 45% as 0.45
        if own and _one_step_from(value, tolerance, own, own):
            tags.add(tag)
    return tags if len(tags) == 1 else set()


def _header_tag(cell: str, scenarios: bool) -> str | None:
    if _CHANGE_HEADER.search(cell):
        return None
    if scenarios:
        if _REVISED_HEADER.search(cell):
            return REVISED
        if _ORIGINAL_HEADER.search(cell) or _CURRENT_HEADER.search(cell):
            return ORIGINAL                              # "Current" beside "Revised" is the original scenario
        return None
    if _PRIOR_HEADER.search(cell):
        return PRIOR
    if _CURRENT_HEADER.search(cell):
        return CURRENT
    return None


def misattributed_figures(text: str, question: str, earlier_user_turns: list[str] | None = None,
                          receipts: list[dict] | None = None,
                          earlier_answers: list[str] | None = None,
                          calculation=None) -> list[tuple[str, str, str]]:
    """(statement, figure, why) for each figure shown in the wrong period or
    scenario. Statements are verbatim, for selective removal."""
    from app.orchestration.numerical_facts import mislabelled_calculation_rows
    typed_mismatches = mislabelled_calculation_rows(text, calculation)
    earlier = [turn for turn in (earlier_user_turns or []) if _amounts(turn)] if _revises_prior_task(question) else []
    facts = tagged_facts(question, earlier, earlier_answers)
    if not facts or len({tag for _, tag in facts}) < 2:
        return typed_mismatches
    scenarios = bool(earlier)
    changed = changed_items(question) if scenarios else []
    # Items the revision recalculated, whether or not the question named them:
    # "Revised variable costs: 2688000 * 0.45" makes the variable-costs row a
    # revised item (its original £1,080,000 cannot stand in the revised column).
    recalculated = [_label_words(receipt.get("label", "")) for receipt in receipts or []
                    if scenarios and receipt.get("label")
                    and provenance(_receipt_result(receipt), facts, receipts) == {REVISED}]
    found: list[tuple[str, str, str]] = []
    columns: dict[int, str] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            columns = {}
            for piece in _statements(stripped):
                if scenarios:
                    continue                             # scenarios are judged in tables only
                context = _sentence_context(piece)
                if context:
                    found += _wrong(piece, material_figures(piece), context, facts, receipts, piece)
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if set(stripped) <= set("|-: "):
            continue
        if not columns and not material_figures(stripped):
            columns = {index: tag for index, cell in enumerate(cells)
                       if (tag := _header_tag(cell, scenarios))}
            continue
        label = cells[0].lower() if cells else ""
        named = any(item in label or label in item for item in changed if label)
        row_words = _label_words(label)
        revised_item = bool(row_words) and any(row_words <= words for words in recalculated)
        if scenarios and not (named or revised_item):
            continue                                     # an unchanged item carries over into the revision
        for index, tag in columns.items():
            if index < len(cells):
                found += _wrong(stripped, material_figures(cells[index]), tag, facts, receipts, stripped)
    return list(dict.fromkeys([*typed_mismatches, *found]))


def _sentence_context(piece: str) -> str | None:
    prior, current = bool(_PRIOR_CUE.search(piece)), bool(_CURRENT_CUE.search(piece))
    if prior == current:
        return None                                      # no period named, or both (a comparison)
    return PRIOR if prior else CURRENT


def _wrong(statement, figures, context, facts, receipts, verbatim) -> list[tuple[str, str, str]]:
    wrong = []
    for shown, value in figures:
        tags = provenance(_amount(shown, value), facts, receipts or [])
        if tags and context not in tags:
            wrong.append((verbatim, shown, f"{shown} belongs to the {' and '.join(sorted(tags))}, "
                                           f"not the {context}"))
    return wrong
