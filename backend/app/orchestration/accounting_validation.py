"""Accounting treatment checks on a composed answer, independent of the model.

The arithmetic check (calculation_service.validate_answer_calculations)
proves that figures add up and that journal entries balance; it says nothing
about whether the treatment is right. A grounded VAT example passed it with
every figure correct and the accounting wrong (24 Oct 2026): input VAT taken
as the VAT-inclusive purchases, VAT added to the company's "total tax
burden", and the tax expense debited when the tax was paid.
accounting_concepts.py checks which standard and method an answer names;
this module checks the treatment it applies.

Each rule here recognises one pattern that is wrong in the ordinary case.
They are validation rules, not accounting answers: a finding is shown to the
reader as something to review and recorded in the audit log; nothing is
rewritten or removed, because a reversal, a refund or an unusual scheme can
make the flagged pattern correct. A rule that cannot read the answer
unambiguously stays silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.orchestration.calculation_service import _CREDIT_HEADER, _DEBIT_HEADER, _amount, _cells


@dataclass(frozen=True)
class AccountingFinding:
    rule: str
    statement: str
    message: str
    # A calculation mismatch: the figure as stated, the canonical result and
    # the output it was compared with.
    stated: str | None = None
    expected: str | None = None
    output: str | None = None


_CASH = re.compile(r"\b(?:cash|bank)\b", re.I)
_TAX_EXPENSE = re.compile(r"\b(?:income|corporat\w*|profits?)?\s*tax\s+(?:expense|charge)\b", re.I)
_PAYABLE = re.compile(r"\b(?:payable|liabilit\w*|accru\w*|provision)\b", re.I)
_REVENUE = re.compile(r"\b(?:revenue|sales|turnover)\b", re.I)
_OUTPUT_TAX = re.compile(r"\b(?:output\s+(?:VAT|GST|tax)|(?:VAT|GST)\s+(?:output|payable|collected))\b", re.I)
_INPUT_TAX = re.compile(r"\b(?:input\s+(?:VAT|GST|tax)|(?:VAT|GST)\s+(?:input|recoverable|receivable|reclaimable))\b",
                        re.I)
_PURCHASE = re.compile(r"\b(?:purchases?|inventory|stock|cost\s+of\s+(?:goods|sales)|COGS|expenses?)\b", re.I)
_REVERSAL = re.compile(r"\b(?:revers\w*|refund\w*|returns?|credit\s+note|correct\w*|write[- ]?off|cancel\w*)\b",
                       re.I)
_INCLUSIVE = re.compile(r"\b(?:(?:VAT|GST|tax)[- ‑]inclusive|incl(?:uding|\.)?\s+(?:of\s+)?(?:VAT|GST|tax)|gross\s+of\s+"
                        r"(?:VAT|GST|tax))\b", re.I)
_MONEY = re.compile(r"[£$€₹]\s?\d[\d,  ]*(?:\.\d+)?|\b\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?\b")
_BURDEN = re.compile(r"\b(?:total\s+tax(?:\s+(?:burden|cost|expense|liability))?|tax\s+burden|tax\s+cost)\b", re.I)
_SALES_TAX = re.compile(r"\b(?:VAT|GST|sales\s+tax)\b", re.I)
_PROFIT_TAX = re.compile(r"\b(?:corporat\w*\s+(?:income\s+)?tax|income\s+tax|profits?\s+tax)\b", re.I)


def _money(text: str) -> list[Decimal]:
    values = []
    for match in _MONEY.finditer(text):
        value = _amount(match.group(0).replace(" ", "").replace(" ", ""))
        if value is not None:
            values.append(value)
    return values


def _journal_entries(answer: str) -> list[list[tuple[str, Decimal | None, Decimal | None, str]]]:
    """Each journal table as (account, debit, credit, row text) rows; a table
    with no debit and credit columns, or with an account in each, is skipped."""
    entries = []
    lines = (answer or "").splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        block = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            block.append((_cells(lines[index]), lines[index].strip()))
            index += 1
        header = block[0][0]
        rows = [(cells, text) for cells, text in block[1:] if not all(set(c) <= set("-: ") for c in cells)]
        debit = next((i for i, cell in enumerate(header) if _DEBIT_HEADER.search(cell)), None)
        credit = next((i for i, cell in enumerate(header) if _CREDIT_HEADER.search(cell)), None)
        account = next((i for i, cell in enumerate(header) if re.search(r"\baccount|particulars|ledger\b", cell, re.I)),
                       None)
        if debit is None or credit is None or account is None or debit == credit:
            continue
        parsed = []
        for cells, text in rows:
            if account >= len(cells) or re.search(r"\btotal\b", cells[account], re.I):
                continue
            side = [_amount(cells[column]) if column < len(cells) else None for column in (debit, credit)]
            parsed.append((cells[account], side[0], side[1], text))
        if parsed:
            entries.append(parsed)
    return entries


def _journal_findings(answer: str) -> list[AccountingFinding]:
    findings = []
    for entry in _journal_entries(answer):
        debited = [(name, text) for name, dr, cr, text in entry if dr and not cr]
        credited = [(name, text) for name, dr, cr, text in entry if cr and not dr]
        if any(_REVERSAL.search(name) for name, *_ in entry):
            continue
        tax_expense = next(((n, t) for n, t in debited if _TAX_EXPENSE.search(n)), None)
        if (tax_expense and any(_CASH.search(n) for n, _ in credited)
                and not any(_PAYABLE.search(n) for n, _ in credited)):
            findings.append(AccountingFinding(
                "tax_expense_on_payment", tax_expense[1],
                "a tax expense is debited against cash. The expense is normally recognised against a tax payable "
                "when it arises; the payment then clears the payable."))
        revenue = next(((n, t) for n, t in debited if _REVENUE.search(n) and not _PAYABLE.search(n)), None)
        if revenue and any(_CASH.search(n) or re.search(r"receivable|debtor", n, re.I) for n, _ in credited):
            findings.append(AccountingFinding(
                "revenue_debited", revenue[1],
                "revenue is debited and cash or a receivable credited, the reverse of a sale. Unless this records a "
                "return or reversal, revenue is credited."))
        output_tax = next(((n, t) for n, t in debited if _OUTPUT_TAX.search(n)), None)
        if output_tax and any(_REVENUE.search(n) for n, _ in credited):
            findings.append(AccountingFinding(
                "output_tax_debited", output_tax[1],
                "output tax is debited in the entry that records the sale. Tax charged on a sale is a liability "
                "and is credited."))
        input_tax = next(((n, t) for n, t in credited if _INPUT_TAX.search(n)), None)
        if input_tax and any(_PURCHASE.search(n) for n, _ in debited):
            findings.append(AccountingFinding(
                "input_tax_credited", input_tax[1],
                "input tax is credited in the entry that records the purchase. Recoverable tax on a purchase is "
                "an asset (or reduces the liability) and is debited."))
    return findings


def _statements(answer: str) -> list[str]:
    pieces = []
    for line in (answer or "").splitlines():
        line = line.strip()
        if line:
            pieces += [line] if line.startswith("|") else re.split(r"(?<=[.;])\s+(?=[A-Z*])", line)
    return pieces


def _tax_base_findings(answer: str) -> list[AccountingFinding]:
    """A tax amount equal to an amount the answer itself calls tax-inclusive:
    the tax within a tax-inclusive amount is a fraction of it, never all of
    it ("Input VAT: £50,000" where "£50,000 of VAT-inclusive purchases")."""
    inclusive: set[Decimal] = set()
    for statement in _statements(answer):
        for match in _INCLUSIVE.finditer(statement):
            near = statement[max(0, match.start() - 60):match.end() + 40]
            inclusive.update(value for value in _money(near) if value > 0)
    findings = []
    if not inclusive:
        return findings
    for statement in _statements(answer):
        if _INCLUSIVE.search(statement) or not (_INPUT_TAX.search(statement) or _OUTPUT_TAX.search(statement)):
            continue
        values = _money(statement)
        # The tax stated, not an operand of its working: the last amount.
        if values and values[-1] in inclusive:
            findings.append(AccountingFinding(
                "tax_equals_inclusive_amount", statement,
                f"the tax amount ({values[-1]:,}) is the whole of an amount described as tax-inclusive. The tax "
                "within a tax-inclusive amount is amount × rate ÷ (1 + rate): one-sixth of it at a 20% rate."))
    return findings


def _collected_tax_findings(answer: str) -> list[AccountingFinding]:
    """A business's own tax cost that adds the VAT or GST it collected."""
    findings = []
    for statement in _statements(answer):
        if (_BURDEN.search(statement) and _SALES_TAX.search(statement) and _PROFIT_TAX.search(statement)
                and re.search(r"\+|\bplus\b|\band\b", statement)):
            findings.append(AccountingFinding(
                "collected_tax_as_cost", statement,
                "VAT or GST is added to the business's own tax cost. A registered business collects it for the tax "
                "authority: it is a liability, not the business's cost (unless it cannot be recovered)."))
    return findings


_IFRS16 = re.compile(r"\bIFRS\s?16\b")
_LESSEE_OPERATING = re.compile(r"\boperating\s+leases?\b[^.]*\b(?:straight[- ]line|single)\s+(?:lease\s+)?(?:expense|cost)\b"
                               r"|\b(?:straight[- ]line|single)\s+(?:lease\s+)?(?:expense|cost)\b[^.]*\boperating\s+leases?\b",
                               re.I)


def _framework_findings(answer: str) -> list[AccountingFinding]:
    """A treatment stated under a standard that does not have it."""
    findings = []
    for statement in _statements(answer):
        if (_IFRS16.search(statement) and _LESSEE_OPERATING.search(statement)
                and not re.search(r"\b(?:ASC\s?842|US\s+GAAP|lessor|unlike|whereas|not\s+under|no\s+longer)\b",
                                  statement, re.I)):
            findings.append(AccountingFinding(
                "ifrs16_lessee_operating_lease", statement,
                "a single straight-line operating-lease expense is stated under IFRS 16. A lessee under IFRS 16 has "
                "no operating-lease classification (short-term and low-value exemptions aside): it depreciates the "
                "right-of-use asset and accrues interest on the lease liability. Straight-line operating-lease cost "
                "is ASC 842."))
    # "Lease payments are classified within operating activities (IFRS 16
    # permits this treatment)" in a lessee answer (27 Oct 2026).
    if _IFRS16.search(answer or "") and not re.search(r"\b(?:ASC\s?842|US\s+GAAP)\b", answer or "", re.I):
        for statement in _statements(answer):
            if (_LEASE_PAYMENTS_OPERATING.search(statement)
                    and not re.search(r"\b(?:short[- ]term|low[- ]value|variable|interest|lessor|not\s+(?:in|within|as)\s+"
                                      r"operating)\b", statement, re.I)):
                findings.append(AccountingFinding(
                    "ifrs16_lease_payments_operating", statement,
                    "lessee lease payments are classified as operating cash flows under IFRS 16. Under IFRS 16 "
                    "(with IAS 7) the principal part of lease payments is a financing cash flow; interest follows "
                    "the entity's IAS 7 policy; only short-term, low-value and variable payments not in the lease "
                    "liability are operating."))
    return findings


_LEASE_PAYMENTS_OPERATING = re.compile(
    r"\blease\s+payments?\b[^.|]*\b(?:classified|presented|shown|reported|included)\s+(?:with)?in\s+operating\s+activit",
    re.I)


_BASIC_EPS = re.compile(r"\bbasic\s+(?:EPS|earnings\s+per\s+share)\b[^\n|]*?(?:=|:|\bis\b)\s*\$?\s?(-?\d+\.\d+)", re.I)
_DILUTED_EPS = re.compile(r"\bdiluted\s+(?:EPS|earnings\s+per\s+share)\b[^\n|]*?(?:=|:|\bis\b)\s*\$?\s?(-?\d+\.\d+)",
                          re.I)


def _eps_findings(answer: str) -> list[AccountingFinding]:
    basic = [Decimal(m.group(1)) for m in _BASIC_EPS.finditer(answer or "")]
    diluted = [(Decimal(m.group(1)), m.group(0)) for m in _DILUTED_EPS.finditer(answer or "")]
    if len(set(basic)) != 1 or not diluted:
        return []
    return [AccountingFinding(
        "diluted_eps_above_basic", text,
        "diluted EPS is above basic EPS. A security that would raise EPS is antidilutive and is left out, so "
        "diluted EPS cannot exceed basic EPS (for a profit).") for value, text in diluted
        if basic[0] > 0 and value > basic[0]]


_AMOUNT_WORDS = r"(?:[£$€₹]\s?)?\d[\d ,  ]*(?:\.\d+)?"
# "an additional debit of £7,279.69", "a £7,279.69 debit is missing", "a
# balancing credit is needed", "debit of £X is required".
_SHORT_SIDE_CLAIM = re.compile(
    rf"\b(?:missing|additional|further|extra|another|balancing|outstanding)\s+(?:{_AMOUNT_WORDS}\s+)?(?P<a>debit|credit)\b"
    rf"|\b(?P<b>debit|credit)\s+(?:of\s+)?(?:{_AMOUNT_WORDS}\s+)?(?:is\s+|would\s+be\s+|must\s+be\s+)?"
    rf"(?:missing|required|needed|outstanding)\b"
    rf"|{_AMOUNT_WORDS}\s+(?P<c>debit|credit)\s+(?:is\s+)?(?:missing|required|needed|outstanding)\b", re.I)


def _journal_sides(answer: str) -> tuple[Decimal, Decimal] | None:
    """Debit and credit totals of the first journal in the answer that does
    not balance (a table, or "Dr … / Cr …" lines), else None."""
    for entry in _journal_entries(answer):
        debit = sum((dr for _, dr, _, _ in entry if dr), Decimal(0))
        credit = sum((cr for _, _, cr, _ in entry if cr), Decimal(0))
        if debit and credit and abs(debit - credit) > Decimal("0.5"):
            return debit, credit
    from app.orchestration.calculation_service import _TEXT_AMOUNT, _TEXT_JOURNAL_LINE
    sides = {"dr": Decimal(0), "cr": Decimal(0)}
    for line in (answer or "").splitlines():
        match = _TEXT_JOURNAL_LINE.match(line)
        amounts = _TEXT_AMOUNT.findall(match.group("rest")) if match else []
        if match and len(amounts) == 1 and (value := _amount(amounts[0])) is not None:
            sides["dr" if match.group("side").lower().startswith("d") else "cr"] += value
    if sides["dr"] and sides["cr"] and abs(sides["dr"] - sides["cr"]) > Decimal("0.5"):
        return sides["dr"], sides["cr"]
    return None


def _balancing_side_findings(answer: str) -> list[AccountingFinding]:
    """The side said to be missing is the side that is already larger. Debits
    of £133,650.60 against credits of £126,370.91 need a further credit, but
    the answer said "a £7,279.69 debit is missing" (28 Oct 2026). Only when
    the answer itself shows the unbalanced entry, so the direction is certain."""
    sides = _journal_sides(answer)
    if sides is None:
        return []
    debit, credit = sides
    short = "credit" if debit > credit else "debit"
    findings = []
    for statement in _statements(answer):
        for match in _SHORT_SIDE_CLAIM.finditer(statement):
            said = (match.group("a") or match.group("b") or match.group("c")).lower()
            if said != short:
                findings.append(AccountingFinding(
                    "balancing_entry_wrong_side", statement,
                    f"the entry's debits ({debit:,}) and credits ({credit:,}) differ, so balancing it needs a further "
                    f"{short} of {abs(debit - credit):,}, not a {said}."))
                break
    return findings


def accounting_findings(answer: str) -> list[AccountingFinding]:
    findings = (_journal_findings(answer) + _tax_base_findings(answer) + _collected_tax_findings(answer)
                + _framework_findings(answer) + _eps_findings(answer) + _balancing_side_findings(answer))
    unique: dict[tuple[str, str], AccountingFinding] = {}
    for finding in findings:
        unique.setdefault((finding.rule, finding.statement), finding)
    return list(unique.values())


REVIEW_PREFIX = "Accounting review needed"


def accounting_review_note(findings: list[AccountingFinding]) -> str | None:
    """The limitation shown with the answer. The arithmetic check only proves
    the figures add up; this says what treatment to review."""
    if not findings:
        return None
    # "The figures add up" is untrue beside an entry that does not balance
    # (balancing_entry_wrong_side, 28 Oct 2026).
    lead = ("the treatment should be checked" if any(f.rule == "balancing_entry_wrong_side" for f in findings)
            else "the figures add up, but the treatment should be checked")
    return f"{REVIEW_PREFIX}: {lead} — " + "; ".join(dict.fromkeys(finding.message for finding in findings))


# ── The application's own calculation (reliability plan phase 2) ─────────────
# When the deterministic engine computed a result from the user's figures, it
# is authoritative for that result. A different figure in the answer for the
# same quantity is disclosed and sent for review, never silently replaced:
# "£6,000 including VAT … input VAT £1,200" is one arithmetic step from the
# user's figures, so the figure checks accepted it.

CALCULATION_PREFIX = "Calculation check"
_OUTPUT_LABELS = {
    "vat_amount": ("vat", "gst", "input tax", "output tax"),
    "output_vat_on_sales": ("output vat", "output tax", "output gst"),
    "input_vat_on_purchases": ("input vat", "input tax", "input gst", "input tax credit"),
    "vat_payable": ("vat payable", "net vat", "vat due", "payable to hmrc", "pay to hmrc", "gst payable"),
    "vat_repayable": ("repayable", "repayment", "refund"),
    "total_including_vat": ("customer pays", "total including", "gross amount"),
    "amount_excluding_vat": ("excluding vat", "net sales", "net amount", "net of vat"),
    "present_value": ("present value",),
    "converted_amount": ("converted", "convert", "worth", "equals", "equivalent"),
}
# How each calculated quantity is named to the reader.
_OUTPUT_NAMES = {
    "vat_amount": "VAT", "output_vat_on_sales": "output VAT", "input_vat_on_purchases": "input VAT",
    "vat_payable": "VAT payable", "vat_repayable": "VAT repayable", "total_including_vat": "total including VAT",
    "amount_excluding_vat": "amount excluding VAT", "present_value": "present value",
    "converted_amount": "converted amount",
}
_PERCENT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?%")


def _written_tolerance(text: str, value: Decimal) -> Decimal:
    """Half a unit of the last place written: £8,638 is £8,638.38 rounded."""
    for match in re.finditer(r"\d[\d,  ]*(?:\.(\d+))?", text):
        digits = match.group(0).replace(",", "").replace(" ", "").replace(" ", "")
        try:
            if Decimal(digits) == value:
                return Decimal("0.5") * Decimal(10) ** -len(match.group(1) or "")
        except ArithmeticError:
            continue
    return Decimal("0.5")


# The figure a label governs: the first figure after it, with only words
# between ("Input VAT you can reclaim is £1,200"), in its own currency.
_GOVERNED_FIGURE = re.compile(
    r"(?P<gap>(?:[^\d£$€₹%.;|]){0,40}?)(?P<symbol>[£$€₹])?\s?(?P<number>\d[\d,  ]*(?:\.\d+)?)\s?(?P<percent>%)?")
# Words between a label and a figure that change what the figure is: "VAT-
# inclusive total £7,200" is not the VAT, "VAT rate 20%" is not an amount.
# A change or an earlier value is not the result either: "profit before tax
# increases by £10,000", "margin falls from 40.17% to 39.10%" (24 Oct 2026).
_BASIS_CHANGE = re.compile(r"\b(?:includ\w*|inclusive|exclud\w*|exclusive|rate|net|gross|total|before|after|"
                           r"per\s+(?:month|quarter|year|annum)|monthly|quarterly|annual\w*|"
                           r"increase\w*|decrease\w*|rises?|rose|fall\w*|fell|drop\w*|change\w*|differ\w*|by|from|"
                           r"was|were|previous\w*|original\w*|old|prior|earlier)\b", re.I)
_SYMBOL_OF = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}


def _governed_figures(statement: str, label: str):
    """(value, currency symbol, is percentage) for the figure each occurrence
    of `label` in the statement governs; a label whose figure is about a
    different basis governs none."""
    for match in re.finditer(rf"\b{re.escape(label)}\b", statement, re.I):
        figure = _GOVERNED_FIGURE.match(statement, match.end())
        if not figure or _BASIS_CHANGE.search(figure.group("gap")):
            continue
        try:
            value = Decimal(re.sub(r"[,  ]", "", figure.group("number")))
        except ArithmeticError:
            continue
        yield value, figure.group("symbol") or "", bool(figure.group("percent"))


# "Dr Lease liability £20,000.00;", "Cr Cash £20,000.00.", "- **Debit** Interest
# expense …", or a journal-table row naming a debit or credit.
_POSTING = re.compile(r"^\W*(?:[A-Za-z][\w ]{0,30}:\s*)?(?:\*\*)?(?:Dr|Cr|Debit|Credit)\b\.?(?:\*\*)?\s", re.I)


def calculation_discrepancies(answer: str, result) -> list[AccountingFinding]:
    """Statements giving a quantity the engine calculated a different value.

    Like is compared with like: the figure the label itself governs, of the
    same kind (an amount or a percentage), in the result's own currency, with
    nothing between them that changes its basis (inclusive or exclusive of
    tax, gross or net, a rate, another period). A figure in another currency
    or on another basis is a different quantity, and is left alone."""
    if result is None or getattr(result, "status", "") != "success":
        return []
    outputs = [o for o in result.outputs if o.value is not None and o.kind in ("money", "percentage")]
    known = [o.value for o in result.outputs if o.value is not None] + [i.value for i in result.inputs]
    # The figures as displayed count too: a payable figure shown tied to the
    # rounded parts (£11.67) can differ from the exact one by a penny.
    for output in result.outputs:
        shown = re.sub(r"[^\d.]", "", output.display_value or "")
        if shown:
            try:
                known.append(Decimal(shown))
            except ArithmeticError:
                pass
    currency = next((i.currency for i in result.inputs if i.currency), None)
    expected_symbol = _SYMBOL_OF.get(currency or "", "")
    findings = []
    # A source marker is not a figure: "input VAT [REF-3]" read as £3 (24 Oct 2026).
    for statement in _statements(re.sub(r"\s*\[REF-\d+\]", "", answer or "")):
        # A journal posting is an amount moved through the account, not the
        # account's balance: "Dr Lease liability £20,000.00" (a year's quarterly
        # payments) was reported as a wrong lease liability (28 Oct 2026).
        if _POSTING.match(statement):
            continue
        for output in outputs:
            labels = _OUTPUT_LABELS.get(output.name, (output.name.replace("_", " "),))
            governed = [(value, symbol) for label in labels
                        for value, symbol, percent in _governed_figures(statement, label)
                        if percent == (output.kind == "percentage")
                        # An amount is compared only when written as money in the result's currency.
                        and (output.kind == "percentage" or (symbol and (not expected_symbol or symbol == expected_symbol)))]
            wrong = [(value, symbol) for value, symbol in governed
                     if not any(abs(value - other) <= _written_tolerance(statement, value) for other in known)]
            if not wrong:
                continue
            label = _OUTPUT_NAMES.get(output.name, output.name.replace("_", " "))
            value, symbol = wrong[0]
            shown = f"{value:,}%" if output.kind == "percentage" else f"{symbol or expected_symbol}{value:,}"
            findings.append(AccountingFinding(
                "calculation_mismatch", statement,
                f"the answer states {shown} for the {label}; the application's exact calculation "
                f"from your figures gives {output.display_value}",
                stated=str(value), expected=str(output.value), output=output.name))
            break
    return findings


def calculation_note(findings: list[AccountingFinding]) -> str | None:
    mismatches = [finding.message for finding in findings if finding.rule == "calculation_mismatch"]
    if not mismatches:
        return None
    return (f"{CALCULATION_PREFIX}: " + "; ".join(dict.fromkeys(mismatches))
            + ". Have the figure reviewed before relying on it.")
