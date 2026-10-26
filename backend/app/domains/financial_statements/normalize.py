"""Normalise a parsed trial balance (Document 04 stage P2, rules SD-004 to
SD-009).

Amounts are exact Decimal. A blank cell, a zero, a dash and an unreadable
value are different states and never coerced into one another. A single
signed "balance" column without a stated convention is not guessed: the
sign convention must be confirmed. Locale-ambiguous numbers ("1.234,56") are
not converted. Every line keeps its sheet and row so it can be traced to the
original cell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .findings import HARD_STOP, INFO, REVIEW, Finding
from .intake import Cell, ParsedSource

ZERO = Decimal("0")
_HEADER_SCAN_ROWS = 25
_ACCOUNT_NAME = re.compile(r"\b(?:account\s*name|account|name|description|ledger|nominal)\b", re.I)
_ACCOUNT_CODE = re.compile(r"\b(?:code|no\.?|number|ref|nominal\s*code|account\s*code|gl)\b", re.I)
_DEBIT = re.compile(r"^\s*(?:debit|dr)\b", re.I)
_CREDIT = re.compile(r"^\s*(?:credit|cr)\b", re.I)
_BALANCE = re.compile(r"\b(?:balance|amount|closing|net)\b", re.I)
_CURRENCY_COL = re.compile(r"\b(?:currency|ccy)\b", re.I)
_SIGN_STATED = re.compile(r"(?:debit|dr)\s*(?:=|is|as)?\s*\+|positive\s*=\s*debit|\(dr\s*\+", re.I)
_THOUSANDS = re.compile(r"£\s*000|'000|\$\s*000|€\s*000|in\s+thousands|\(000s?\)", re.I)
_TOTAL = re.compile(r"^\s*(?:grand\s+)?(?:sub)?totals?\b", re.I)
_DASHES = {"-", "–", "—", "nil"}
_PLAIN = re.compile(r"^\(?-?[£$€₹¥]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?-?$|^\(?-?[£$€₹¥]?\d+(?:\.\d+)?\)?-?$")
_EUROPEAN = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$|^-?\d+,\d{1,2}$")
_SYMBOLS = re.compile(r"[£$€₹¥]")


@dataclass(frozen=True)
class Amount:
    value: Decimal | None
    status: str                    # PRESENT | ZERO | BLANK | INVALID | LOCALE_AMBIGUOUS
    raw: str


def parse_amount(text: str) -> Amount:
    raw = (text or "").strip()
    if not raw:
        return Amount(None, "BLANK", raw)
    if raw.lower() in _DASHES:
        return Amount(ZERO, "ZERO", raw)
    compact = re.sub(r"\s", "", raw)
    if _EUROPEAN.match(compact):
        return Amount(None, "LOCALE_AMBIGUOUS", raw)
    if not _PLAIN.match(compact):
        return Amount(None, "INVALID", raw)
    negative = compact.startswith("(") and compact.endswith(")") or compact.startswith("-") or compact.endswith("-")
    digits = re.sub(r"[^\d.]", "", compact)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return Amount(None, "INVALID", raw)
    value = -value if negative else value
    return Amount(value, "ZERO" if value == 0 else "PRESENT", raw)


@dataclass(frozen=True)
class TBLine:
    key: str                       # stable account key: code, else name
    account_code: str
    account_name: str
    debit: Amount
    credit: Amount
    currency: str
    sheet: str
    row: int
    hidden: bool = False

    @property
    def ref(self) -> str:
        return f"{self.sheet}!R{self.row}"

    @property
    def net_debit(self) -> Decimal:
        return (self.debit.value or ZERO) - (self.credit.value or ZERO)

    def to_dict(self) -> dict:
        return {"key": self.key, "account_code": self.account_code, "account_name": self.account_name,
                "debit": str(self.debit.value) if self.debit.value is not None else None,
                "credit": str(self.credit.value) if self.credit.value is not None else None,
                "debit_status": self.debit.status, "credit_status": self.credit.status,
                "currency": self.currency, "source": self.ref, "hidden": self.hidden}


@dataclass
class NormalizedTB:
    lines: list[TBLine] = field(default_factory=list)
    control_totals: list[tuple[str, Amount, Amount]] = field(default_factory=list)   # (ref, debit, credit)
    units: str = "units"
    sign_convention: str = "DEBIT_CREDIT_COLUMNS"
    year_columns: tuple[str, ...] = ()
    findings: list[Finding] = field(default_factory=list)


def _find_header(rows: list[list[Cell]]):
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        texts = [re.sub(r"[_\-]+", " ", c.text) for c in row]     # "account_code" is "account code"
        debit = next((i for i, t in enumerate(texts) if _DEBIT.search(t)), None)
        credit = next((i for i, t in enumerate(texts) if _CREDIT.search(t)), None)
        balance = next((i for i, t in enumerate(texts) if _BALANCE.search(t)), None)
        name = next((i for i, t in enumerate(texts) if _ACCOUNT_NAME.search(t)
                     and not _ACCOUNT_CODE.fullmatch(t.strip())
                     and i not in (debit, credit) and not re.search(r"code|no\.?$|number", t, re.I)), None)
        if name is None:
            continue
        if (debit is not None and credit is not None) or balance is not None:
            code = next((i for i, t in enumerate(texts) if i != name and re.search(r"code|no\.?$|number|^ref$", t, re.I)), None)
            currency = next((i for i, t in enumerate(texts) if _CURRENCY_COL.search(t)), None)
            column = lambda i: None if i is None else row[i].column  # noqa: E731 — the sheet's own column number
            return index, {"name": column(name), "code": column(code), "debit": column(debit), "credit": column(credit),
                           "balance": column(balance) if debit is None or credit is None else None,
                           "currency": column(currency)}
    return None, None


def normalize(parsed: ParsedSource) -> NormalizedTB:
    tb = NormalizedTB()
    rows = parsed.rows
    header_index, cols = _find_header(rows)
    if cols is None:
        tb.findings.append(Finding("AMBIGUOUS_SCHEMA", HARD_STOP,
                                   "No account and debit/credit (or balance) columns were found.", "SD-004"))
        return tb
    header_row = rows[header_index]
    title_text = " ".join(c.text for r in rows[:header_index + 1] for c in r)
    if _THOUSANDS.search(title_text):
        tb.units = "thousands"
        tb.findings.append(Finding("UNITS_THOUSANDS", INFO, "Amounts are stated in thousands.", "SD-004"))
    tb.year_columns = tuple(sorted({y for c in header_row for y in re.findall(r"\b(?:19|20)\d{2}\b", c.text)}))
    single = cols["balance"] is not None
    if single:
        tb.sign_convention = "SIGNED_BALANCE"
        if not _SIGN_STATED.search(title_text):
            tb.findings.append(Finding("SIGN_UNRESOLVED", HARD_STOP,
                                       "A single balance column has no stated sign convention (is debit positive?). "
                                       "Confirm it before the balances are used.", "SD-007"))
    symbols: set[str] = set()

    def text(row: list[Cell], column: int | None) -> str:
        if column is None:
            return ""
        return next((c.text for c in row if c.column == column), "")

    for row in rows[header_index + 1:]:
        if row and row[0].sheet != header_row[0].sheet:
            continue
        name, code = text(row, cols["name"]), text(row, cols["code"])
        if single:
            amount = parse_amount(text(row, cols["balance"]))
            if amount.value is not None and amount.value < 0:
                debit, credit = Amount(ZERO, "BLANK", ""), Amount(-amount.value, amount.status, amount.raw)
            else:
                debit, credit = amount, Amount(None, "BLANK", "")
        else:
            debit, credit = parse_amount(text(row, cols["debit"])), parse_amount(text(row, cols["credit"]))
        if not name and not code and debit.status == "BLANK" and credit.status == "BLANK":
            continue
        for amount in (debit, credit):
            symbols |= set(_SYMBOLS.findall(amount.raw))
        if _TOTAL.match(name or code):
            tb.control_totals.append((f"{row[0].sheet}!R{row[0].row}", debit, credit))
            continue
        tb.lines.append(TBLine(key=code or name, account_code=code, account_name=name or code, debit=debit,
                               credit=credit, currency=text(row, cols["currency"]).upper(), sheet=row[0].sheet,
                               row=row[0].row, hidden=any(c.hidden for c in row)))
    if len(symbols) > 1:
        tb.findings.append(Finding("MIXED_CURRENCY", HARD_STOP,
                                   f"Amounts use more than one currency symbol ({', '.join(sorted(symbols))}).", "SD-005"))
    currencies = {line.currency for line in tb.lines if line.currency}
    if len(currencies) > 1:
        tb.findings.append(Finding("MIXED_CURRENCY", HARD_STOP,
                                   f"Lines are in more than one currency ({', '.join(sorted(currencies))}); they "
                                   f"cannot be summed without an approved translation.", "SD-005"))
    return tb
